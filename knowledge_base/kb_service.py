#!/usr/bin/env python3
"""
知识库服务 (KB Service) - 重构版

统一接口：所有文档类型（Markdown/PDF）使用相同的处理流程
存储结构：${GITHUB_AGENT_STATEDIR}/
  - knowledge_base/chips/       # 芯片文档
  - knowledge_base/best_practices/  # 最佳实践
  - chroma_db/                  # ChromaDB 向量数据库
"""

import os
import sys
import json
import hashlib
import logging
import requests
import requests.adapters
import urllib3
from pathlib import Path
from typing import List, Dict, Any, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

try:
    from .schema import DocumentChunk, ChunkMetadata, QueryResult, DocType
    from .document_processor import DocumentProcessor, process_document
except ImportError:
    from schema import DocumentChunk, ChunkMetadata, QueryResult, DocType
    from document_processor import DocumentProcessor, process_document


class SimpleEmbedding:
    """Ollama 嵌入生成器"""
    
    MODEL_DIMENSIONS = {
        "nomic-embed-text": 768,
        "nomic-embed-text:latest": 768,
        "bge-m3": 1024,
        "bge-m3:latest": 1024,
        "all-minilm": 384,
    }
    
    def __init__(self, model: str = "nomic-embed-text", host: str = "http://localhost:11434"):
        self.model = model
        self.hosts = [h.strip() for h in host.split(',')] if ',' in host else [host]
        self._host_index = 0
        self._host_lock = threading.Lock()
        self._cache = {}
        
        if model in self.MODEL_DIMENSIONS:
            self._dimension = self.MODEL_DIMENSIONS[model]
        else:
            self._dimension = 768
        logger.info(f"使用维度: {self._dimension} (模型: {model})")
        
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,
            pool_maxsize=50,
            max_retries=urllib3.util.Retry(total=3, backoff_factor=0.1)
        )
        self._session.mount('http://', adapter)
    
    def _get_host(self) -> str:
        with self._host_lock:
            host = self.hosts[self._host_index]
            self._host_index = (self._host_index + 1) % len(self.hosts)
            return host
    
    def get_dimension(self) -> int:
        return self._dimension
    
    def embed(self, text: str) -> List[float]:
        if not text or not text.strip():
            return [0.0] * self._dimension
        
        text = text.strip()[:8000]
        cache_key = hashlib.md5(text.encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        host = self._get_host()
        response = self._session.post(
            f"{host}/api/embed",
            json={"model": self.model, "input": text},
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        
        embedding = result.get("embeddings", [[]])[0] if "embeddings" in result else result.get("embedding", [])
        
        if len(embedding) != self._dimension:
            raise ValueError(f"维度不匹配: 期望 {self._dimension}, 实际 {len(embedding)}")
        
        self._cache[cache_key] = embedding
        return embedding


class ChromaVectorStore:
    """ChromaDB 向量存储"""
    
    def __init__(self, persist_dir: str, collection_name: str = "knowledge_base"):
        try:
            import chromadb
            self.chromadb = chromadb
        except ImportError:
            raise RuntimeError("chromadb 未安装: pip install chromadb")
        
        self.persist_dir = persist_dir
        self.client = self.chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"ChromaDB 已初始化: {persist_dir}")
    
    def add_chunk(self, chunk: DocumentChunk, embedding: List[float]) -> str:
        """添加单个 chunk"""
        self.collection.add(
            ids=[chunk.embedding_id],
            embeddings=[embedding],
            documents=[chunk.content],
            metadatas=[chunk.metadata.to_dict()]
        )
        return chunk.embedding_id
    
    def search(
        self, 
        query_embedding: List[float], 
        top_k: int = 5,
        filters: Dict[str, Any] = None
    ) -> List[QueryResult]:
        """
        搜索相似 chunks
        
        Args:
            query_embedding: 查询向量
            top_k: 返回结果数
            filters: 元数据过滤条件，如 {"vendor": "bosch"}
        """
        try:
            # 构建 where 条件
            where_clause = filters if filters else None
            
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, max(1, self.collection.count())),
                where=where_clause,
                include=["documents", "metadatas", "distances"]
            )
            
            output = []
            for i in range(len(results['ids'][0])):
                distance = results['distances'][0][i]
                similarity = 1 - distance  # cosine distance to similarity
                
                metadata = ChunkMetadata.from_dict(results['metadatas'][0][i])
                
                output.append(QueryResult(
                    content=results['documents'][0][i],
                    metadata=metadata,
                    similarity=round(similarity, 4)
                ))
            return output
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []
    
    def delete_by_source(self, source: str):
        """删除指定来源的所有 chunks"""
        try:
            results = self.collection.get(
                where={"source": source},
                include=[]
            )
            if results['ids']:
                self.collection.delete(ids=results['ids'])
                logger.info(f"已删除 {len(results['ids'])} 个 chunks: {source}")
        except Exception as e:
            logger.error(f"删除失败: {e}")
    
    def get_stored_hashes(self) -> Dict[str, str]:
        """获取已存储文件的 hash（用于增量检测）"""
        try:
            results = self.collection.get(include=["metadatas"])
            hashes = {}
            seen = set()
            
            for meta in results['metadatas']:
                source = meta.get('source', '')
                file_hash = meta.get('file_hash', '')
                if source and file_hash and source not in seen:
                    hashes[source] = file_hash
                    seen.add(source)
            return hashes
        except Exception as e:
            logger.error(f"获取 hash 失败: {e}")
            return {}
    
    def count(self) -> int:
        try:
            return self.collection.count()
        except:
            return 0


class KnowledgeBaseService:
    """知识库服务"""
    
    def __init__(self, 
                 embedding_model: str = None, 
                 embedding_host: str = None,
                 chroma_dir: str = None):
        
        # 状态目录
        statedir = Path(os.environ.get("GITHUB_AGENT_STATEDIR", "/tmp/github-agent-state"))
        statedir.mkdir(parents=True, exist_ok=True)
        
        # 知识库目录
        self.kb_dirs = {
            "chips": statedir / "knowledge_base" / "chips",
            "practices": statedir / "knowledge_base" / "best_practices"
        }
        for d in self.kb_dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        
        # 初始化组件
        self.embedding_model = embedding_model or "nomic-embed-text"
        self.embedding_host = embedding_host or "http://localhost:11434"
        self.embedder = SimpleEmbedding(model=self.embedding_model, host=self.embedding_host)
        
        # ChromaDB
        chroma_path = chroma_dir or str(statedir / "chroma_db")
        self.vector_store = ChromaVectorStore(persist_dir=chroma_path)
        
        # 文档处理器
        self.doc_processor = DocumentProcessor()
        
        # 后台加载
        threading.Thread(target=self._sync_knowledge, daemon=True).start()
    
    def _sync_knowledge(self):
        """同步知识库（增量加载）"""
        time.sleep(1)  # 等待服务启动
        
        stored_hashes = self.vector_store.get_stored_hashes()
        stats = {"added": 0, "unchanged": 0, "failed": 0}
        
        for dir_path, doc_type in [(self.kb_dirs["chips"], DocType.CHIP), 
                                   (self.kb_dirs["practices"], DocType.PRACTICE)]:
            if not dir_path.exists():
                continue
            
            for file in dir_path.glob("*"):
                if file.suffix.lower() not in ['.md', '.pdf']:
                    continue
                
                try:
                    status = self._process_file(file, doc_type, stored_hashes)
                    stats[status] += 1
                except Exception as e:
                    stats["failed"] += 1
                    logger.warning(f"处理失败 {file}: {e}")
        
        total = stats["added"] + stats["unchanged"]
        if total > 0:
            logger.info(f"加载完成: 新增 {stats['added']}, 未变更 {stats['unchanged']}, 失败 {stats['failed']}")
    
    def _process_file(self, file: Path, doc_type: DocType, stored_hashes: Dict[str, str]) -> str:
        """
        处理单个文件
        
        Returns:
            "added" / "unchanged" / "failed"
        """
        file_key = str(file)
        
        # 计算文件 hash
        if file.suffix.lower() == '.pdf':
            stat = file.stat()
            file_hash = hashlib.md5(f"{stat.st_size}_{stat.st_mtime}".encode()).hexdigest()
        else:
            file_hash = hashlib.md5(file.read_bytes()).hexdigest()
        
        # 检查是否已存在
        if file_key in stored_hashes and stored_hashes[file_key] == file_hash:
            return "unchanged"
        
        # 删除旧数据
        if file_key in stored_hashes:
            self.vector_store.delete_by_source(file_key)
        
        # 解析文档
        doc = self.doc_processor.process(file, doc_type)
        
        # 生成 embeddings 并存储
        for chunk in doc.chunks:
            embedding = self.embedder.embed(chunk.content[:2000])
            chunk.metadata.file_hash = file_hash
            self.vector_store.add_chunk(chunk, embedding)
        
        logger.info(f"已加载: {file.name} ({len(doc.chunks)} chunks)")
        return "added"
    
    def query(self, query_text: str, top_k: int = 3, filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """查询知识库"""
        start = time.time()
        
        query_embedding = self.embedder.embed(query_text)
        results = self.vector_store.search(query_embedding, top_k, filters)
        
        return {
            "query": query_text,
            "results": [
                {
                    "content": r.content,
                    "metadata": r.metadata.to_dict(),
                    "similarity": r.similarity
                }
                for r in results
            ],
            "total_found": len(results),
            "elapsed_ms": round((time.time() - start) * 1000, 2)
        }
    
    def reload(self) -> Dict[str, Any]:
        """重新加载知识库"""
        logger.info("重新加载知识库...")
        self._sync_knowledge()
        return {"status": "success", "documents": self.vector_store.count()}
    
    def health_check(self) -> bool:
        try:
            return len(self.embedder.embed("test")) > 0
        except:
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "embedding_model": self.embedding_model,
            "total_documents": self.vector_store.count()
        }


class KBRequestHandler(BaseHTTPRequestHandler):
    kb_service: KnowledgeBaseService = None
    
    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")
    
    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
    
    def do_GET(self):
        if self.path == "/health":
            healthy = self.kb_service.health_check() if self.kb_service else False
            self._send_json({
                "status": "healthy" if healthy else "unhealthy",
                "documents": self.kb_service.get_stats()["total_documents"] if self.kb_service else 0
            })
        elif self.path == "/stats":
            self._send_json(self.kb_service.get_stats() if self.kb_service else {})
        elif self.path == "/reload":
            self._send_json(self.kb_service.reload() if self.kb_service else {})
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode()) if post_data else {}
        except:
            data = {}
        
        if self.path == "/query":
            query = data.get("query", "")
            top_k = data.get("top_k", 3)
            filters = data.get("filters")  # 支持 metadata 过滤
            
            if not query:
                self._send_json({"error": "Missing query"}, 400)
                return
            
            result = self.kb_service.query(query, top_k, filters)
            self._send_json(result)
        
        elif self.path == "/reload":
            self._send_json(self.kb_service.reload())
        
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()


def run_server(host: str = "0.0.0.0", port: int = 8000,
               embedding_model: str = None, embedding_host: str = None):
    logger.info(f"启动知识库服务 {host}:{port}")
    
    kb_service = KnowledgeBaseService(
        embedding_model=embedding_model,
        embedding_host=embedding_host
    )
    
    KBRequestHandler.kb_service = kb_service
    
    server = HTTPServer((host, port), KBRequestHandler)
    logger.info(f"知识库服务已启动 http://{host}:{port}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("正在关闭服务...")
        server.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument("--embedding-host", default="http://localhost:11434")
    args = parser.parse_args()
    
    run_server(
        host=args.host,
        port=args.port,
        embedding_model=args.embedding_model,
        embedding_host=args.embedding_host
    )
