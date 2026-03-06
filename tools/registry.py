import logging
from typing import Dict, Any
from tools.k8s_actions import KubernetesActions

logger = logging.getLogger(__name__)

class ToolRegistry:
    def __init__(self, use_mock: bool = False):
        self.k8s_actions = KubernetesActions(use_mock=use_mock)
        
        # String to function map matching the Prompt declarations
        self._registry = {
            "rollback_deployment": self.k8s_actions.rollback_deployment,
            "scale_deployment": self.k8s_actions.scale_deployment,
            "restart_pods": self.k8s_actions.restart_pods,
            "noop_require_human": self._noop_require_human
        }

    def _noop_require_human(self, **kwargs) -> Dict[str, Any]:
        """Safe handoff tool when the agent is unsure or lacks DB access."""
        return {
            "success": False, 
            "message": "Agent elected to handoff. Human intervention required."
        }

    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a registered string tool with safety boundaries.
        """
        logger.info(f"Execution Sandbox requested tool: {tool_name} with params: {parameters}")
        
        if tool_name not in self._registry:
            logger.error(f"Unregistered tool invoked! Preveting execution: {tool_name}")
            return {"success": False, "error": f"Tool '{tool_name}' is not in the safe sandbox registry."}
            
        command = self._registry[tool_name]
        try:
            result = command(**parameters)
            logger.info(f"Tool execution result: {result}")
            return result
        except Exception as e:
            logger.error(f"Execution failed inside sandbox: {str(e)}")
            return {"success": False, "error": f"Sandbox execution crash: {str(e)}"}
