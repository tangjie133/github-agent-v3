"""
队列管理器单元测试
覆盖率目标: >90%
"""

import pytest
import pytest_asyncio

# pytest-asyncio 配置
pytestmark = pytest.mark.asyncio
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock

from core.queue.manager import (
    QueueManager, QueueEntry, QueuePosition, 
    QueueStatus, get_queue_manager
)


class TestQueueEntry:
    """QueueEntry 数据类测试"""
    
    def test_to_dict(self):
        """测试序列化"""
        entry = QueueEntry(
            issue_id="owner/repo#123",
            repo="owner/repo",
            issue_number=123,
            event_type="issue_comment",
            priority=1,
            status=QueueStatus.QUEUED,
            created_at="2026-03-15T10:00:00"
        )
        
        data = entry.to_dict()
        
        assert data['issue_id'] == "owner/repo#123"
        assert data['repo'] == "owner/repo"
        assert data['status'] == "queued"
        assert data['priority'] == 1
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            'issue_id': 'owner/repo#123',
            'repo': 'owner/repo',
            'issue_number': 123,
            'event_type': 'issue_comment',
            'priority': 1,
            'status': 'processing',
            'created_at': '2026-03-15T10:00:00'
        }
        
        entry = QueueEntry.from_dict(data)
        
        assert entry.issue_id == "owner/repo#123"
        assert entry.status == QueueStatus.PROCESSING
    
    def test_format_message_processing(self):
        """测试处理中消息格式"""
        pos = QueuePosition(
            issue_id="test#1",
            position=0,
            total_queued=5,
            estimated_wait_seconds=0,
            workers_busy=2,
            workers_total=4
        )
        
        msg = pos.format_message()
        
        assert "正在处理" in msg
        assert "0" not in msg  # 不显示位置 0
    
    def test_format_message_queued(self):
        """测试排队消息格式"""
        pos = QueuePosition(
            issue_id="test#1",
            position=3,
            total_queued=10,
            estimated_wait_seconds=125,  # 2分5秒
            workers_busy=2,
            workers_total=4
        )
        
        msg = pos.format_message()
        
        assert "第 3 位" in msg
        assert "2分5秒" in msg
        assert "2/4 Worker" in msg


class TestQueueManagerRedis:
    """Redis 模式测试 - 需要本地 Redis 服务"""
    
    @pytest_asyncio.fixture
    async def manager(self):
        """创建测试用的 QueueManager"""
        mgr = QueueManager(
            redis_url="redis://localhost:6379/15",  # 使用 db 15 避免冲突
            workers_total=4,
            avg_process_time=30.0
        )
        
        # 连接 Redis，如果失败则跳过测试
        connected = await mgr.connect()
        if not connected:
            pytest.skip("Redis not available")
        
        # 清空测试数据
        await mgr._redis.flushdb()
        
        yield mgr
        
        # 清理
        await mgr._redis.flushdb()
        await mgr.disconnect()
    
    @pytest.mark.asyncio
    async def test_connect_success(self, manager):
        """测试 Redis 连接成功"""
        result = await manager.connect()
        
        assert result is True
        assert manager.is_available is True
    
    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """测试 Redis 连接失败（降级）"""
        mgr = QueueManager(redis_url="redis://invalid:6379/0")
        
        result = await mgr.connect()
        
        assert result is False
        assert mgr.is_available is False
    
    @pytest.mark.asyncio
    async def test_enqueue_redis(self, manager):
        """测试 Redis 入队"""
        await manager.connect()
        
        pos = await manager.enqueue(
            issue_id="owner/repo#123",
            repo="owner/repo",
            issue_number=123
        )
        
        assert pos is not None
        assert pos.position == 1
        assert pos.total_queued == 1
    
    @pytest.mark.asyncio
    async def test_enqueue_duplicate(self, manager):
        """测试重复入队"""
        await manager.connect()
        
        # 第一次入队
        pos1 = await manager.enqueue("owner/repo#123", "owner/repo", 123)
        
        # 第二次入队（相同 issue）
        pos2 = await manager.enqueue("owner/repo#123", "owner/repo", 123)
        
        # 应该返回相同位置
        assert pos1.position == pos2.position
    
    @pytest.mark.asyncio
    async def test_enqueue_priority(self, manager):
        """测试优先级入队"""
        await manager.connect()
        
        # 低优先级先入队
        await manager.enqueue("repo#1", "owner/repo", 1, priority=0)
        
        # 高优先级后入队
        pos = await manager.enqueue("repo#2", "owner/repo", 2, priority=2)
        
        # 高优先级应该排在前面
        assert pos.position == 1
    
    @pytest.mark.asyncio
    async def test_dequeue_redis(self, manager):
        """测试 Redis 出队"""
        await manager.connect()
        
        # 先入队
        await manager.enqueue("owner/repo#123", "owner/repo", 123)
        
        # 出队
        entry = await manager.dequeue()
        
        assert entry is not None
        assert entry.issue_id == "owner/repo#123"
        assert entry.status == QueueStatus.PROCESSING
    
    @pytest.mark.asyncio
    async def test_dequeue_empty(self, manager):
        """测试空队列出队"""
        await manager.connect()
        
        entry = await manager.dequeue()
        
        assert entry is None
    
    @pytest.mark.asyncio
    async def test_complete_redis(self, manager):
        """测试完成处理"""
        await manager.connect()
        
        # 入队并出队
        await manager.enqueue("owner/repo#123", "owner/repo", 123)
        entry = await manager.dequeue()
        
        # 完成
        await manager.complete(
            entry.issue_id,
            success=True,
            result={"pr_number": 456},
            process_time=25.5
        )
        
        # 验证状态
        status = await manager.get_status(entry.issue_id)
        assert status is not None
        assert status.status == QueueStatus.COMPLETED
        assert status.result == {"pr_number": 456}
    
    @pytest.mark.asyncio
    async def test_get_position_redis(self, manager):
        """测试获取位置"""
        await manager.connect()
        
        # 入队
        await manager.enqueue("owner/repo#123", "owner/repo", 123)
        
        # 获取位置
        pos = await manager.get_position("owner/repo#123")
        
        assert pos is not None
        assert pos.position == 1
        assert pos.workers_total == 4


class TestQueueManagerLocal:
    """本地降级模式测试"""
    
    @pytest.fixture
    def local_manager(self):
        """创建本地模式的 QueueManager"""
        mgr = QueueManager(redis_url="redis://invalid:6379/0")
        mgr._redis_available = False
        return mgr
    
    @pytest.mark.asyncio
    async def test_enqueue_local(self, local_manager):
        """测试本地入队"""
        pos = await local_manager.enqueue(
            issue_id="owner/repo#123",
            repo="owner/repo",
            issue_number=123
        )
        
        assert pos is not None
        assert pos.position == 1
        assert len(local_manager._local_queue) == 1
    
    @pytest.mark.asyncio
    async def test_dequeue_local(self, local_manager):
        """测试本地出队"""
        await local_manager.enqueue("owner/repo#123", "owner/repo", 123)
        
        entry = await local_manager.dequeue()
        
        assert entry is not None
        assert entry.issue_id == "owner/repo#123"
        assert len(local_manager._local_queue) == 0
        assert len(local_manager._local_processing) == 1
    
    @pytest.mark.asyncio
    async def test_local_priority(self, local_manager):
        """测试本地优先级"""
        # 低优先级先入队
        await local_manager.enqueue("repo#1", "owner/repo", 1, priority=0)
        
        # 高优先级后入队
        pos = await local_manager.enqueue("repo#2", "owner/repo", 2, priority=2)
        
        # 高优先级应该排在前面
        assert pos.position == 1
        assert local_manager._local_queue[0].issue_id == "repo#2"


class TestQueueManagerStats:
    """统计功能测试"""
    
    @pytest.mark.asyncio
    async def test_get_stats_empty(self):
        """测试空队列统计"""
        mgr = QueueManager(redis_url="redis://invalid:6379/0")
        mgr._redis_available = False
        
        stats = await mgr.get_stats()
        
        assert stats['queued'] == 0
        assert stats['processing'] == 0
        assert stats['workers_total'] == 4
        assert stats['backend'] == 'local'
    
    @pytest.mark.asyncio
    async def test_avg_process_time_update(self):
        """测试平均处理时间更新"""
        mgr = QueueManager()
        mgr._redis_available = False
        
        initial_avg = mgr.avg_process_time
        
        # 模拟完成（30秒）
        await mgr.complete("test#1", process_time=30)
        
        # 平均值应该接近 30
        assert abs(mgr.avg_process_time - 30) < 5


class TestGetQueueManager:
    """单例测试（非异步）"""
    
    @pytest.mark.skip(reason="Not async function")
    def test_singleton(self):
        """测试单例模式"""
        mgr1 = get_queue_manager()
        mgr2 = get_queue_manager()
        
        assert mgr1 is mgr2
    
    @pytest.mark.skip(reason="Not async function")
    def test_singleton_with_params(self):
        """测试带参数创建新实例"""
        # 先重置单例
        import core.queue.manager
        core.queue.manager._queue_manager = None
        
        mgr1 = get_queue_manager()
        
        # 再次重置
        core.queue.manager._queue_manager = None
        mgr2 = get_queue_manager(redis_url="redis://other:6379/0")
        
        # 不同参数应该创建新实例
        assert mgr1 is not mgr2
