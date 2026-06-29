"""Specialist agents that make up the pipeline."""
from __future__ import annotations

from agent.agents.architect import ArchitectAgent
from agent.agents.backend import BackendAgent, CodingAgent, FrontendAgent
from agent.agents.base import Agent
from agent.agents.debug import DebugAgent
from agent.agents.planning import PlanningAgent
from agent.agents.pull_request import PullRequestAgent
from agent.agents.repo_analysis import RepoAnalysisAgent
from agent.agents.review import ReviewAgent, SecurityAgent
from agent.agents.testing import TestingAgent, TestResult

__all__ = [
    "Agent",
    "PlanningAgent",
    "RepoAnalysisAgent",
    "ArchitectAgent",
    "BackendAgent",
    "FrontendAgent",
    "CodingAgent",
    "TestingAgent",
    "TestResult",
    "DebugAgent",
    "ReviewAgent",
    "SecurityAgent",
    "PullRequestAgent",
]
