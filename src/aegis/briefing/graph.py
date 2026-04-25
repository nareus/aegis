"""Build the LangGraph briefing graph."""

from langgraph.graph import StateGraph, START, END

from aegis.briefing.state import BriefingState
from aegis.briefing.nodes import (
    init_run,
    fetch_github,
    fetch_hn,
    fetch_jobs,
    check_fetches,
    route_after_fetches,
    prioritize,
    synthesize,
    self_evaluate,
    maybe_refine,
    route_after_evaluate,
    degraded_output,
    persist,
)


def build_briefing_graph() -> StateGraph:
    """Construct and return the compiled briefing graph.

    Graph topology:
        init_run
           |
           +-- fetch_github
           +-- fetch_hn
           +-- fetch_jobs
           |
        check_fetches
          /         \\
     all fail      >=1 ok
         |            |
    degraded      prioritize
         |            |
         |        synthesize
         |            |
         |        self_evaluate
         |            |
         |        maybe_refine -> synthesize (if score < 0.7 and iterations < 2)
         |            |
         +--- persist ----> END
    """
    graph = StateGraph(BriefingState)

    # Nodes
    graph.add_node("init_run", init_run)
    graph.add_node("fetch_github", fetch_github)
    graph.add_node("fetch_hn", fetch_hn)
    graph.add_node("fetch_jobs", fetch_jobs)
    graph.add_node("check_fetches", check_fetches)
    graph.add_node("prioritize", prioritize)
    graph.add_node("synthesize", synthesize)
    graph.add_node("self_evaluate", self_evaluate)
    graph.add_node("maybe_refine", maybe_refine)
    graph.add_node("degraded_output", degraded_output)
    graph.add_node("persist", persist)

    # Entry
    graph.add_edge(START, "init_run")

    # Fan-out: init_run -> all fetch nodes in parallel
    graph.add_edge("init_run", "fetch_github")
    graph.add_edge("init_run", "fetch_hn")
    graph.add_edge("init_run", "fetch_jobs")

    # Fan-in: all fetch nodes -> check_fetches
    graph.add_edge("fetch_github", "check_fetches")
    graph.add_edge("fetch_hn", "check_fetches")
    graph.add_edge("fetch_jobs", "check_fetches")

    # Conditional: check_fetches -> prioritize or degraded_output
    graph.add_conditional_edges(
        "check_fetches",
        route_after_fetches,
        {"prioritize": "prioritize", "degraded_output": "degraded_output"},
    )

    # Main path
    graph.add_edge("prioritize", "synthesize")
    graph.add_edge("synthesize", "self_evaluate")
    graph.add_edge("self_evaluate", "maybe_refine")

    # Conditional: maybe_refine -> synthesize (loop) or persist
    graph.add_conditional_edges(
        "maybe_refine",
        route_after_evaluate,
        {"synthesize": "synthesize", "persist": "persist"},
    )

    # Degraded path -> persist
    graph.add_edge("degraded_output", "persist")

    # End
    graph.add_edge("persist", END)

    return graph
