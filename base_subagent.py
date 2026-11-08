"""
Base Subagent Class
Abstract base class for all subagents.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseSubagent(ABC):
    """Abstract base class for all subagents."""

    def __init__(self, name: str):
        """
        Initialize the subagent.

        Args:
            name: Subagent name
        """
        self.name = name

    @abstractmethod
    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the subagent's specialized task.

        Args:
            input_data: Input data for the task

        Returns:
            Result dictionary
        """
        pass
