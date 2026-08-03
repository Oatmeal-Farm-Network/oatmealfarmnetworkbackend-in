# --- test_redis.py --- (Test Redis connection and setup)
"""
Quick test script to verify Redis connection and configuration.
Run this after installing Redis to ensure everything is working.
"""
import sys
from config import (
    REDIS_ENABLED, REDIS_HOST, REDIS_PORT, REDIS_PASSWORD,
    REDIS_DB, REDIS_SSL, SHORT_TERM_N, get_redis_url, redis_connection_mode
)
from redis_client import test_redis_connection, get_redis_client
from message_buffer import message_buffer


def test_checkpoint_redis():
    """Test Redis connection for checkpointing (needs bytes, not strings)."""
    print("\n" + "=" * 60)
    print("Testing Redis Checkpointing Connection")
    print("=" * 60)
    
    if not REDIS_ENABLED:
        print("[FAIL] Redis is disabled in config")
        return False
    
    try:
        from langgraph.checkpoint.redis import RedisSaver
        redis_url = get_redis_url()
        print(f"[INFO] Redis connection mode: {redis_connection_mode()}")
        checkpointer = RedisSaver(redis_url)
        print("[OK] Redis checkpointing client created successfully")
        checkpointer.setup()
        print("[OK] Redis checkpoint indexes verified")
        return True
    except ImportError:
        print("[FAIL] langgraph-checkpoint-redis not installed")
        print("   Run: pip install langgraph-checkpoint-redis")
        return False
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_message_buffer():
    """Test message buffer functionality."""
    print("\n" + "=" * 60)
    print("Testing Message Buffer")
    print("=" * 60)
    
    if not message_buffer.client:
        print("[FAIL] Message buffer client not available")
        return False
    
    test_thread_id = "test_thread_123"
    
    try:
        # Clear any existing test data
        message_buffer.clear_thread(test_thread_id)
        
        # Add test messages
        print(f"Adding test messages to thread: {test_thread_id}")
        message_buffer.push_message(test_thread_id, {"role": "user", "content": "Hello, I need help with my farm"})
        message_buffer.push_message(test_thread_id, {"role": "assistant", "content": "I'd be happy to help! What do you need?"})
        message_buffer.push_message(test_thread_id, {"role": "user", "content": "I'm growing tomatoes"})
        
        # Retrieve messages
        messages = message_buffer.get_last_n(test_thread_id, 3)
        print(f"[OK] Retrieved {len(messages)} messages")
        
        for i, msg in enumerate(messages, 1):
            print(f"  {i}. [{msg['role']}]: {msg['content'][:50]}...")

        # Ensure oldest -> newest ordering
        if messages and messages[0]["content"] != "Hello, I need help with my farm":
            raise AssertionError("get_last_n ordering is incorrect (expected oldest -> newest)")

        # Ensure count never exceeds N
        overfill_count = SHORT_TERM_N + 5
        for i in range(overfill_count):
            message_buffer.push_message(test_thread_id, {"role": "user", "content": f"overflow-{i}"})
        trimmed_messages = message_buffer.get_last_n(test_thread_id, SHORT_TERM_N)
        if len(trimmed_messages) > SHORT_TERM_N:
            raise AssertionError("Message buffer exceeded SHORT_TERM_N after trim")
        
        # Cleanup
        message_buffer.clear_thread(test_thread_id)
        print("[OK] Message buffer test passed")
        return True
        
    except Exception as e:
        print(f"[FAIL] Message buffer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Redis Setup Test")
    print("=" * 60)
    print(f"Configuration:")
    print(f"  REDIS_ENABLED: {REDIS_ENABLED}")
    print(f"  REDIS_HOST: {REDIS_HOST}")
    print(f"  REDIS_PORT: {REDIS_PORT}")
    print(f"  REDIS_DB: {REDIS_DB}")
    print(f"  REDIS_SSL: {REDIS_SSL}")
    print(f"  SHORT_TERM_N: {SHORT_TERM_N}")
    
    # Test basic connection
    print("\n" + "=" * 60)
    print("Testing Basic Redis Connection")
    print("=" * 60)
    basic_ok = test_redis_connection()
    
    # Test checkpointing
    checkpoint_ok = test_checkpoint_redis()
    
    # Test message buffer
    buffer_ok = test_message_buffer()
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Basic Connection: {'[PASS]' if basic_ok else '[FAIL]'}")
    print(f"Checkpointing: {'[PASS]' if checkpoint_ok else '[FAIL]'}")
    print(f"Message Buffer: {'[PASS]' if buffer_ok else '[FAIL]'}")
    
    if basic_ok and checkpoint_ok and buffer_ok:
        print("\n[SUCCESS] All tests passed! Redis is ready to use.")
        return 0
    else:
        print("\n[WARN] Some tests failed. Check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

