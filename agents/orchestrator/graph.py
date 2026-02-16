"""
LangGraph-based Orchestrator Workflow.
Implements a stateful graph for intelligent task routing and multi-agent coordination.
"""

from typing import TypedDict, List, Dict, Any, Annotated
from datetime import datetime
import logging

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import get_settings
from src.auth.token_broker import get_token_broker

logger = logging.getLogger(__name__)


# ============================================================================
# State Schema
# ============================================================================

class OrchestratorState(TypedDict):
    """State for the orchestrator workflow."""
    # Input
    user_query: str
    access_token: str
    context_id: str
    
    # Discovered agents
    available_agents: List[Dict[str, Any]]
    
    # Task decomposition
    task_plan: List[Dict[str, Any]]  # [{agent_url, agent_name, task, step}]
    
    # Execution tracking
    current_task_index: int
    task_results: List[Dict[str, Any]]  # [{step, agent, result}]
    
    # Approval tracking
    approval_status: str | None  # "pending", "approved", "denied"
    
    # Messages for LLM conversation
    messages: Annotated[List, "Messages for LLM context"]
    
    # Final output
    final_response: str
    error: str | None


# ============================================================================
# Graph Nodes
# ============================================================================

async def discover_agents_node(state: OrchestratorState) -> OrchestratorState:
    """
    Node 1: Discover available agents via A2A Card Resolution.
    """
    logger.info("🔍 [LangGraph] Discovering agents...")
    
    # Import here to avoid circular dependencies
    from agents.orchestrator.agent import OrchestratorAgent
    
    # Create temporary orchestrator instance for discovery
    orchestrator = OrchestratorAgent()
    agents = await orchestrator.discover_agents()
    
    logger.info(f"✅ [LangGraph] Discovered {len(agents)} agents")
    
    return {
        **state,
        "available_agents": agents,
        "messages": state.get("messages", []) + [
            AIMessage(content=f"Discovered {len(agents)} agents: {', '.join(a['name'] for a in agents)}")
        ]
    }


async def plan_tasks_node(state: OrchestratorState) -> OrchestratorState:
    """
    Node 2: Use LLM to decompose user query into ordered tasks.
    """
    logger.info("📋 [LangGraph] Planning tasks with LLM...")
    
    settings = get_settings()
    llm = ChatOpenAI(
        model="gpt-4o",
        api_key=settings.openai_api_key,
        temperature=0
    )
    
    # Build agent context for LLM
    agent_descriptions = "\n".join([
        f"- {a['name']} ({a['url']}): {a['description']}\n  Skills: {', '.join(a['skills'])}"
        for a in state["available_agents"]
    ])
    
    system_prompt = f"""You are an intelligent task planner for a multi-agent system.

Available Agents:
{agent_descriptions}

Your task: Break down the user's request into ordered steps that can be executed by these agents.
Return a JSON array of tasks in this exact format:
[
  {{"step": 1, "agent_name": "HR Agent", "agent_url": "http://localhost:8001", "task": "Create employee record for John"}},
  {{"step": 2, "agent_name": "IT Agent", "agent_url": "http://localhost:8002", "task": "Provision accounts for new employee"}}
]

Rules:
- Only use agents that are actually available
- Tasks should be specific and actionable
- Order tasks logically (dependencies first)
- Return ONLY the JSON array, no other text
"""
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"User request: {state['user_query']}")
    ]
    
    response = await llm.ainvoke(messages)
    
    # Parse the response
    import json
    try:
        task_plan = json.loads(response.content.strip())
        logger.info(f"✅ [LangGraph] Created plan with {len(task_plan)} tasks")
    except json.JSONDecodeError as e:
        logger.error(f"❌ Failed to parse LLM response: {e}")
        task_plan = []
    
    return {
        **state,
        "task_plan": task_plan,
        "current_task_index": 0,
        "task_results": [],
        "messages": state.get("messages", []) + [
            AIMessage(content=f"Created execution plan with {len(task_plan)} steps")
        ]
    }


async def execute_task_node(state: OrchestratorState) -> OrchestratorState:
    """
    Node 3: Execute the current task by calling the appropriate agent.
    """
    task_idx = state["current_task_index"]
    task_plan = state["task_plan"]
    
    if task_idx >= len(task_plan):
        # No more tasks to execute
        return state
    
    current_task = task_plan[task_idx]
    logger.info(f"🚀 [LangGraph] Executing task {task_idx + 1}/{len(task_plan)}: {current_task['task']}")
    
    # Import here to avoid circular dependencies
    from agents.orchestrator.agent import OrchestratorAgent
    
    # Get token broker for token exchange
    token_broker = get_token_broker()
    
    # Dynamically determine agent key from discovered agents
    agent_key = None
    target_agent = None
    
    for agent in state["available_agents"]:
        if agent["url"] == current_task["agent_url"]:
            target_agent = agent
            # Derive key from agent name (e.g., "HR Agent" -> "hr_agent")
            agent_key = agent["name"].lower().replace(" ", "_")
            break
    
    if not agent_key:
        # Fallback: derive from agent name in task
        agent_key = current_task["agent_name"].lower().replace(" ", "_")
    
    # Get scopes from config dynamically
    from src.config_loader import load_yaml_config
    config = load_yaml_config()
    agents_config = config.get("agents", {})
    
    # Find agent config by key or name
    agent_config = agents_config.get(agent_key)
    if agent_config:
        # Get scopes from config
        agent_scopes = agent_config.get("scopes", [])
        if not agent_scopes:
            # Fallback: derive from agent name
            scope_prefix = agent_key.replace("_agent", "")
            agent_scopes = [f"{scope_prefix}:read", f"{scope_prefix}:write"]
    else:
        # Fallback: derive scopes from agent name
        scope_prefix = agent_key.replace("_agent", "")
        agent_scopes = [f"{scope_prefix}:read", f"{scope_prefix}:write"]

    
    try:
        # Exchange token for this specific agent
        agent_token = await token_broker.exchange_token_for_agent(
            source_token=state["access_token"],
            agent_key=agent_key,
            target_audience=current_task["agent_name"].lower().replace(" ", "-"),
            target_scopes=agent_scopes.get(agent_key, [])
        )
        
        # Call the agent
        orchestrator = OrchestratorAgent()
        result = await orchestrator.call_agent(
            agent_url=current_task["agent_url"],
            query=current_task["task"],
            access_token=agent_token
        )
        
        logger.info(f"✅ [LangGraph] Task {task_idx + 1} completed successfully")
        
        task_result = {
            "step": current_task["step"],
            "agent": current_task["agent_name"],
            "task": current_task["task"],
            "result": result,
            "success": True
        }
        
        # Check if this was an approval task and update approval status
        new_approval_status = state.get("approval_status")
        if "approval" in current_task["agent_name"].lower():
            result_lower = str(result).lower()
            if "approved" in result_lower or "approval granted" in result_lower:
                new_approval_status = "approved"
                logger.info("✅ [LangGraph] Approval granted")
            elif "denied" in result_lower or "rejected" in result_lower:
                new_approval_status = "denied"
                logger.warning("❌ [LangGraph] Approval denied")
            else:
                new_approval_status = "pending"
        
    except Exception as e:
        logger.error(f"❌ [LangGraph] Task {task_idx + 1} failed: {e}")
        task_result = {
            "step": current_task["step"],
            "agent": current_task["agent_name"],
            "task": current_task["task"],
            "result": str(e),
            "success": False
        }
        new_approval_status = state.get("approval_status")
    
    return {
        **state,
        "current_task_index": task_idx + 1,
        "task_results": state["task_results"] + [task_result],
        "approval_status": new_approval_status,
        "messages": state.get("messages", []) + [
            AIMessage(content=f"Completed: {current_task['task']}")
        ]
    }


async def aggregate_results_node(state: OrchestratorState) -> OrchestratorState:
    """
    Node 4: Aggregate all task results into a final response.
    """
    logger.info("📊 [LangGraph] Aggregating results...")
    
    # Build final response
    results_summary = []
    for task_result in state["task_results"]:
        status = "✅" if task_result["success"] else "❌"
        results_summary.append(
            f"{status} Step {task_result['step']}: {task_result['agent']} - {task_result['task']}\n"
            f"   Result: {task_result['result']}"
        )
    
    final_response = "\n\n".join(results_summary)
    
    logger.info("✅ [LangGraph] Workflow completed")
    
    return {
        **state,
        "final_response": final_response
    }


# ============================================================================
# Conditional Routing
# ============================================================================

def should_continue_execution(state: OrchestratorState) -> str:
    """
    Decides whether to continue executing tasks or move to aggregation.
    Stops workflow if approval was denied.
    """
    # Check if approval was denied
    if state.get("approval_status") == "denied":
        logger.warning("⚠️ [LangGraph] Stopping workflow - approval denied")
        return "aggregate"
    
    # Continue if there are more tasks
    if state["current_task_index"] < len(state["task_plan"]):
        return "execute_task"
    else:
        return "aggregate"


# ============================================================================
# Graph Construction
# ============================================================================

def create_orchestrator_graph() -> StateGraph:
    """
    Creates the LangGraph workflow for the orchestrator.
    
    Graph Flow:
    START → discover_agents → plan_tasks → execute_task → (loop or aggregate) → END
    """
    workflow = StateGraph(OrchestratorState)
    
    # Add nodes
    workflow.add_node("discover_agents", discover_agents_node)
    workflow.add_node("plan_tasks", plan_tasks_node)
    workflow.add_node("execute_task", execute_task_node)
    workflow.add_node("aggregate", aggregate_results_node)
    
    # Define edges
    workflow.set_entry_point("discover_agents")
    workflow.add_edge("discover_agents", "plan_tasks")
    workflow.add_edge("plan_tasks", "execute_task")
    
    # Conditional routing after task execution
    workflow.add_conditional_edges(
        "execute_task",
        should_continue_execution,
        {
            "execute_task": "execute_task",  # Loop back for next task
            "aggregate": "aggregate"          # Move to final aggregation
        }
    )
    
    workflow.add_edge("aggregate", END)
    
    return workflow.compile()


# ============================================================================
# Main Execution Function
# ============================================================================

async def run_orchestrator_workflow(
    user_query: str,
    access_token: str,
    context_id: str = "default"
) -> Dict[str, Any]:
    """
    Execute the orchestrator workflow using LangGraph.
    
    Args:
        user_query: The user's request
        access_token: OAuth2 access token for the user
        context_id: Session context identifier
    
    Returns:
        Final state with aggregated results
    """
    logger.info(f"🚀 [LangGraph] Starting orchestrator workflow for: {user_query}")
    
    # Create the graph
    graph = create_orchestrator_graph()
    
    # Initialize state
    initial_state: OrchestratorState = {
        "user_query": user_query,
        "access_token": access_token,
        "context_id": context_id,
        "available_agents": [],
        "task_plan": [],
        "current_task_index": 0,
        "task_results": [],
        "approval_status": None,
        "messages": [HumanMessage(content=user_query)],
        "final_response": "",
        "error": None
    }
    
    # Run the graph
    try:
        final_state = await graph.ainvoke(initial_state)
        logger.info("✅ [LangGraph] Workflow completed successfully")
        return final_state
    except Exception as e:
        logger.error(f"❌ [LangGraph] Workflow failed: {e}")
        return {
            **initial_state,
            "error": str(e),
            "final_response": f"Workflow failed: {e}"
        }
