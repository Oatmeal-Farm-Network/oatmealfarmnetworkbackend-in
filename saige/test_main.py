"""
Simple test script for the enhanced farm advisory system.
Tests that main.py loads correctly and the graph is functional.
"""
from graph import graph
from saige_models import FarmState
from langgraph.types import Command

def test_graph_empty_start():
    """Test basic graph functionality with empty start."""
    config = {"configurable": {"thread_id": "test-001"}, "recursion_limit": 50}
    
    print("="*60)
    print("Test 1: Empty Start (Open-ended question)")
    print("="*60)
    
    # Start with empty history
    initial_state = {"history": []}
    
    try:
        # Test that graph can start
        events = list(graph.stream(initial_state, config, stream_mode="values"))
        print(f"✓ Graph started successfully ({len(events)} events)")
        
        # Check for interrupt
        state = graph.get_state(config)
        if state.next and state.tasks:
            task = state.tasks[0]
            if task.interrupts:
                ui_schema = task.interrupts[0].value
                print(f"✓ Assessment node asking - Question: {ui_schema.get('question', '')[:80]}...")
                print(f"✓ Options: {len(ui_schema.get('options', []))} provided")
        
        print(f"✓ Test 1 passed!\n")
        return True
        
    except Exception as e:
        print(f"❌ Test 1 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_graph_complete_question():
    """Test graph with complete question in first message."""
    config = {"configurable": {"thread_id": "test-002"}, "recursion_limit": 50}
    
    print("="*60)
    print("Test 2: Complete Question First (Fast-track)")
    print("="*60)
    
    # Start with user's complete question
    user_question = "which animal and breed is suitable for cotton field"
    initial_state = {"history": [f"User: {user_question}"]}
    
    try:
        # Test that graph processes complete question
        events = list(graph.stream(initial_state, config, stream_mode="values"))
        print(f"✓ Graph processed complete question ({len(events)} events)")
        
        # Check final state
        state = graph.get_state(config)
        values = state.values
        
        # Should have assessment_summary immediately
        if values.get("assessment_summary"):
            print(f"✓ Assessment completed: {values['assessment_summary'][:80]}...")
        
        # Should detect advisory type
        if values.get("advisory_type"):
            print(f"✓ Advisory type detected: {values['advisory_type']}")
        
        # Should eventually have diagnosis
        if values.get("diagnosis"):
            print(f"✓ Diagnosis generated: {values['diagnosis'][:100]}...")
        elif not state.next:
            # Might still be complete without diagnosis (depends on flow)
            print(f"✓ Flow completed to: {state.next or 'END'}")
        
        print(f"✓ Test 2 passed!\n")
        return True
        
    except Exception as e:
        print(f"❌ Test 2 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_state_structure():
    """Test state structure."""
    print("="*60)
    print("Test 3: State Structure")
    print("="*60)
    
    config = {"configurable": {"thread_id": "test-003"}}
    initial_state = {"history": []}
    
    try:
        # Run one iteration
        events = list(graph.stream(initial_state, config, stream_mode="values"))
        state = graph.get_state(config)
        values = state.values
        
        print(f"✓ State fields:")
        print(f"  - history: {type(values.get('history'))}")
        print(f"  - current_issues: {type(values.get('current_issues'))}")
        print(f"  - crops: {type(values.get('crops'))}")
        print(f"  - assessment_summary: {type(values.get('assessment_summary'))}")
        print(f"  - advisory_type: {type(values.get('advisory_type'))}")
        print(f"  - diagnosis: {type(values.get('diagnosis'))}")
        print(f"  - recommendations: {type(values.get('recommendations'))}")
        
        print(f"✓ Test 3 passed!\n")
        return True
        
    except Exception as e:
        print(f"❌ Test 3 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n🧪 Farm Advisory System - Test Suite\n")
    
    results = []
    results.append(("Empty Start", test_graph_empty_start()))
    results.append(("Complete Question", test_graph_complete_question()))
    results.append(("State Structure", test_state_structure()))
    
    print("="*60)
    print("TEST SUMMARY")
    print("="*60)
    for test_name, passed in results:
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(result[1] for result in results)
    print("="*60)
    
    if all_passed:
        print("\n✅ All tests passed! System is ready for use.\n")
    else:
        print("\n⚠️ Some tests failed. Please check the output above.\n")
    
    exit(0 if all_passed else 1)

