"""
Configuration loader for SS Automation.
設定檔載入與管理模組
"""

import os
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(Exception):
    """Configuration related errors."""
    pass


class Config:
    """
    Application configuration manager.

    Loads settings from YAML file and provides typed access to configuration values.
    Supports environment variable overrides for sensitive data.
    """

    _instance: "Config | None" = None
    _config: dict[str, Any] = {}

    def __new__(cls) -> "Config":
        """Singleton pattern to ensure single config instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, config_path: str | Path | None = None) -> None:
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to settings.yaml. If None, uses default location.

        Raises:
            ConfigurationError: If config file cannot be loaded.
        """
        if config_path is None:
            # Default: look for config relative to project root
            project_root = Path(__file__).parent.parent
            config_path = project_root / "config" / "settings.yaml"

        config_path = Path(config_path)

        if not config_path.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in config file: {e}")

        # Apply environment variable overrides
        self._apply_env_overrides()

        # Ensure required directories exist
        self._ensure_directories()

    def _apply_env_overrides(self) -> None:
        """Override config values with environment variables."""
        env_mappings = {
            "SS_EMAIL_SENDER": ("email", "sender"),
            "SS_EMAIL_PASSWORD": ("email", "password"),
            "SS_SMTP_SERVER": ("email", "smtp_server"),
            "SS_DATABASE_PATH": ("paths", "database"),
        }

        for env_var, config_path in env_mappings.items():
            value = os.environ.get(env_var)
            if value:
                self._set_nested(config_path, value)

    def _set_nested(self, path: tuple[str, ...], value: Any) -> None:
        """Set a nested configuration value."""
        current = self._config
        for key in path[:-1]:
            current = current.setdefault(key, {})
        current[path[-1]] = value

    def _ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        paths_config = self._config.get("paths", {})

        for key in ["input_dir", "output_dir", "archive_dir"]:
            dir_path = paths_config.get(key)
            if dir_path:
                Path(dir_path).mkdir(parents=True, exist_ok=True)

        # Ensure database directory exists
        db_path = paths_config.get("database")
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Ensure log directory exists
        log_file = self._config.get("logging", {}).get("file")
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        Get a configuration value by nested keys.

        Args:
            *keys: Nested keys to traverse (e.g., "calculation", "lead_time_days")
            default: Default value if key not found

        Returns:
            Configuration value or default

        Example:
            >>> config.get("calculation", "lead_time_days", default=30)
            30
        """
        current = self._config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    @property
    def paths(self) -> dict[str, str]:
        """Get paths configuration."""
        return self._config.get("paths", {})

    @property
    def calculation(self) -> dict[str, Any]:
        """Get calculation parameters."""
        return self._config.get("calculation", {})

    @property
    def outlier_detection(self) -> dict[str, Any]:
        """Get outlier detection settings."""
        return self._config.get("outlier_detection", {})

    @property
    def change_validation(self) -> dict[str, Any]:
        """Get change validation thresholds."""
        return self._config.get("change_validation", {})

    @property
    def column_aliases(self) -> dict[str, list[str]]:
        """Get column name aliases for data loading."""
        return self._config.get("column_aliases", {})

    @property
    def plan_column_aliases(self) -> dict[str, list[str]]:
        """Get plan data column aliases."""
        return self._config.get("plan_column_aliases", {})

    @property
    def email(self) -> dict[str, Any]:
        """Get email notification settings."""
        return self._config.get("email", {})


# Global config instance
config = Config()

# Auto-load configuration on module import
try:
    config.load()
except ConfigurationError as e:
    import warnings
    warnings.warn(f"Failed to load config: {e}")


def load_config(config_path: str | Path | None = None) -> Config:
    """
    Load and return the global configuration.

    Args:
        config_path: Optional path to settings.yaml

    Returns:
        Configured Config instance
    """
    config.load(config_path)
    return config