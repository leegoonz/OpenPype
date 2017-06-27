import pprint

from maya import cmds

import pyblish.api
import colorbleed.api
import colorbleed.maya.lib as lib


class ValidateModelContent(pyblish.api.InstancePlugin):
    """Adheres to the content of 'model' family

    - Must have one top group.
    - Must only contain: transforms, meshes and groups

    """

    order = colorbleed.api.ValidateContentsOrder
    hosts = ["maya"]
    families = ["colorbleed.model"]
    label = "Model Content"
    actions = [colorbleed.api.SelectInvalidAction]

    @classmethod
    def get_invalid(cls, instance):

        pprint.pprint(instance.data)

        content_instance = instance.data.get("setMembers", None)
        if not content_instance:
            cls.log.error("Instance has no nodes!")
            return True

        # Ensure only valid node types
        allowed = ('mesh', 'transform', 'nurbsCurve')
        nodes = cmds.ls(content_instance, long=True)
        valid = cmds.ls(content_instance, long=True, type=allowed)
        invalid = set(nodes) - set(valid)

        if invalid:
            cls.log.error("These nodes are not allowed: %s" % invalid)
            return list(invalid)

        # Top group
        assemblies = cmds.ls(content_instance, assemblies=True, long=True)
        if len(assemblies) != 1:
            cls.log.error("Must have exactly one top group")
            if len(assemblies) == 0:
                cls.log.warning("No top group found. "
                                "(Are there objects in the instance?)")
            return assemblies or True

        if not valid:
            cls.log.error("No valid nodes in the instance")
            return True

        def _is_visible(node):
            """Return whether node is visible"""
            return lib.is_visible(node,
                                  displayLayer=False,
                                  intermediateObject=True,
                                  parentHidden=True,
                                  visibility=True)

        # The roots must be visible (the assemblies)
        for assembly in assemblies:
            if not _is_visible(assembly):
                cls.log.error("Invisible assembly (root node) is not "
                              "allowed: {0}".format(assembly))
                invalid.add(assembly)

        # Ensure at least one shape is visible
        shapes = cmds.ls(valid, long=True, shapes=True)
        if not any(_is_visible(shape) for shape in shapes):
            cls.log.error("No visible shapes in the model instance")
            invalid.update(shapes)

        return list(invalid)

    def process(self, instance):

        invalid = self.get_invalid(instance)

        if invalid:
            raise RuntimeError("Model content is invalid. See log.")
