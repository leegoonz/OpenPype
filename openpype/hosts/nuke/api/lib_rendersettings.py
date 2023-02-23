
from openpype.lib import Logger
from openpype.settings import (
    get_current_project_settings,
    get_system_settings
)


class RenderFarmSettings:
    """ Class for getting farm settings from project settings
    """
    log = Logger.get_logger("RenderFarmSettings")

    _active_farm_module: str = None
    _farm_modules: list = [
        "deadline", "muster", "royalrender"]
    _farm_plugins: dict = {
        "deadline": "NukeSubmitDeadline"
    }
    _creator_farm_keys: list = [
        "chunk_size", "priority", "concurrent_tasks"]

    def __init__(self, project_settings=None):
        """ Get project settings and active farm module
        """
        self._project_settings = (
            project_settings or get_current_project_settings()
        )
        # Get active farm module from system settings
        self._get_active_farm_module_from_system_settings()

    def _get_active_farm_module_from_system_settings(self):
        """ Get active farm module from system settings
        """
        active_modules = [
            module_
            for module_ in self._farm_modules
            if get_system_settings()["modules"][module_]["enabled"]
        ]
        if not active_modules:
            raise ValueError((
                "No active farm module found in system settings."
            ))
        if len(active_modules) > 1:
            raise ValueError((
                "Multiple active farm modules "
                "found in system settings. {}".format(active_modules)
            ))

        self._active_farm_module = active_modules.pop()

    @property
    def active_farm_module(self):
        return self._active_farm_module

    def get_rendering_attributes(self):
        ''' Get rendering attributes from project settings

        Returns:
            dict: rendering attributes
        '''
        return_dict = {}
        farm_plugin = self._farm_plugins.get(self.active_farm_module)

        if farm_plugin:
            raise ValueError((
                "Farm plugin \"{}\" not found in farm plugins."
            ).format(farm_plugin))

        # Get farm module settings
        module_settings = self._project_settings[self.active_farm_module]

        # Get farm plugin settings
        farm_plugin_settings = (
            module_settings["publish"][farm_plugin])

        # Get all keys from farm_plugin_settings
        for key in self._creator_farm_keys:
            if key not in farm_plugin_settings:
                self.log.warning((
                    "Key \"{}\" not found in farm plugin \"{}\" settings."
                ).format(key, farm_plugin))
                continue
            return_dict[key] = farm_plugin_settings[key]

        return return_dict
