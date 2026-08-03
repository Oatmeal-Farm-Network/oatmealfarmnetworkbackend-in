"""
Test script to simulate exact API flow with complete question in first message.
This mimics what happens when user sends "which animal and breed is suitable for cotton field"
"""

try:
    from graph import graph
    from langgraph.types import Command
    
    print("="*80)
    print("TESTING API FLOW: Complete Question in First Message")
    print("="*80)
    
    # Simulate exactly what the API does
    user_input = "which animal and breed is suitable for cotton field"
    thread_id = "test-api-flow-001"
    
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
    
    # Check if thread exists (should be empty for new conversation)
    state = graph.get_state(config)
    print(f"\n[Test] Initial state - Next nodes: {state.next}")
    
    if not state.next:
        # Start new conversation (exactly like API does)
        print(f"\n[Test] Starting new conversation")
        print(f"[Test] User input: {user_input}")
        initial_history = [f"User: {user_input}"]
        print(f"[Test] Initial history: {initial_history}")
        
        # Stream events
        print(f"\n[Test] Streaming graph...")
        events = graph.stream({"history": initial_history}, config, stream_mode="values")
        
        events_list = []
        for i, event in enumerate(events):
            print(f"\n[Test] Event {i+1} - Keys: {list(event.keys())}")
            events_list.append(event)
        
        # Get final state
        final_state = graph.get_state(config)
        print(f"\n[Test] Final state - Next nodes: {final_state.next}")
        
        if final_state.next:
            print(f"[Test] Status: Requires input (interrupt)")
            if final_state.tasks and final_state.tasks[0].interrupts:
                ui = final_state.tasks[0].interrupts[0].value
                print(f"[Test] Question: {ui.get('question', 'N/A')[:100]}...")
        else:
            print(f"[Test] Status: Complete")
            final_values = final_state.values
            
            print(f"\n[Test] Final Values:")
            print(f"  - assessment_summary: {final_values.get('assessment_summary', 'None')}")
            print(f"  - advisory_type: {final_values.get('advisory_type', 'None')}")
            print(f"  - current_issues: {final_values.get('current_issues', 'None')}")
            print(f"  - crops: {final_values.get('crops', 'None')}")
            print(f"  - diagnosis: {final_values.get('diagnosis', 'None')[:200] if final_values.get('diagnosis') else 'None'}...")
            print(f"  - recommendations count: {len(final_values.get('recommendations', []))}")
            
            if final_values.get('diagnosis'):
                print(f"\n✓✓✓ SUCCESS! Fast-track worked - got diagnosis directly")
            else:
                print(f"\n⚠️⚠️⚠️ ISSUE! Assessment might have completed but no diagnosis generated")
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)
    
except Exception as e:
    print(f"\n❌ Test failed with error: {e}")
    import traceback
    traceback.print_exc()

