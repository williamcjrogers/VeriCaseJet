"""
Plugin System for Contract Intelligence
Manages different contract types (JCT, NEC, FIDIC) as plugins
"""

import logging
from typing import Dict, Type, List, Optional, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class ContractPlugin(ABC):
    """Base class for contract plugins"""

    CONTRACT_NAME: str
    CONTRACT_VERSION: str

    @classmethod
    @abstractmethod
    def analyze_text_for_entitlements(cls, text: str) -> Dict[str, Any]:
        """Analyze text for entitlements and risks"""
        pass

    @classmethod
    @abstractmethod
    def get_clause(cls, clause_number: str) -> Optional[Any]:
        """Get clause details"""
        pass


class PluginRegistry:
    """Registry for contract plugins"""

    _plugins: Dict[str, Type[ContractPlugin]] = {}

    @classmethod
    def register(cls, plugin: Type[ContractPlugin]):
        """Register a new contract plugin"""
        key = f"{plugin.CONTRACT_NAME} {plugin.CONTRACT_VERSION}"
        cls._plugins[key] = plugin
        logger.info(f"Registered contract plugin: {key}")

    @classmethod
    def get_plugin(cls, contract_name: str) -> Optional[Type[ContractPlugin]]:
        """Get a plugin by contract name"""
        return cls._plugins.get(contract_name)

    @classmethod
    def get_all_plugins(cls) -> List[str]:
        """Get list of all registered plugins"""
        return list(cls._plugins.keys())
