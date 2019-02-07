# Copyright (c) 2014 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
A Toolkit engine for Mari
"""

import os
import logging
import mari
import mari.utils
import sgtk
from sgtk import TankError

SHOTGUN_APP_PALETTE_PREFIX = "panel_"
MARI_MAIN_WINDOW_WIDGET_NAME = "MainWindow"

class MariEngine(sgtk.platform.Engine):
    """
    The engine class
    """

    @property
    def context_change_allowed(self):
        """
        Whether the engine allows a context change without the need for a restart.
        """
        return True

    @property
    def host_info(self):
        """
        :returns: A dictionary with information about the application hosting this engine.

        The returned dictionary is of the following form on success:

            {
                "name": "Mari",
                "version": "1.2.3",
            }

        The returned dictionary is of following form on an error preventing
        the version identification.

            {
                "name": "Mari",
                "version: "unknown"
            }
        """
        host_info = {"name": "Mari", "version": "unknown"}

        try:
            mari_version = mari.app.version()

            host_info["version"] = "%s.%s.%s" % (
                mari_version.major(),
                mari_version.minor(),
                mari_version.revision()
            )

        except:
            # Fallback to initialization value above
            pass

        return host_info

    def pre_app_init(self):
        """
        Engine construction/setup done before any apps are initialized
        """
        self.log_debug("%s: Initializing..." % self)

        # check that this version of Mari is supported:
        MIN_VERSION = (2,6,1) # completely unsupported below this!
        MAX_VERSION = (4,2) # untested above this so display a warning

        mari_version = mari.app.version()
        if (mari_version.major() < MIN_VERSION[0]
            or (mari_version.major() == MIN_VERSION[0] and mari_version.minor() < MIN_VERSION[1])):
            # this is a completely unsupported version of Mari!
            raise TankError("This version of Mari (%d.%dv%d) is not supported by Shotgun Toolkit.  The"
                            "minimum required version is %d.%dv%d."
                            % (mari_version.major(), mari_version.minor(), mari_version.revision(),
                               MIN_VERSION[0], MIN_VERSION[1], MIN_VERSION[2]))
        elif (mari_version.major() > MAX_VERSION[0]
              or (mari_version.major() == MAX_VERSION[0] and mari_version.minor() > MAX_VERSION[1])):
            # this is an untested version of Mari
            msg = ("The Shotgun Pipeline Toolkit has not yet been fully tested with Mari %d.%dv%d. "
                   "You can continue to use the Toolkit but you may experience bugs or "
                   "instability.  Please report any issues you see to support@shotgunsoftware.com"
                   % (mari_version.major(), mari_version.minor(), mari_version.revision()))

            if (self.has_ui
                and "SGTK_MARI_VERSION_WARNING_SHOWN" not in os.environ
                and mari_version.major() >= self.get_setting("compatibility_dialog_min_version")):
                # show the warning dialog the first time:
                mari.utils.message(msg, "Shotgun")
                os.environ["SGTK_MARI_VERSION_WARNING_SHOWN"] = "1"

            self.log_warning(msg)

        # cache handles to the various manager instances:
        tk_mari = self.import_module("tk_mari")
        self.__geometry_mgr = tk_mari.GeometryManager()
        self.__project_mgr = tk_mari.ProjectManager()
        self.__metadata_mgr = tk_mari.MetadataManager()

    def post_app_init(self):
        """
        Do any initialization after apps have been loaded
        """
        self.create_menu()

        # connect to Mari project events:
        mari.utils.connect(mari.projects.opened, self.__on_project_opened)
        # mari.utils.connect(mari.projects.saved, self.__on_project_saved)

        self._run_app_instance_commands()

    def post_context_change(self, old_context, new_context):
        """
        Handles post-context-change requirements for Mari.

        :param old_context: The sgtk.context.Context being switched away from.
        :param new_context: The sgtk.context.Context being switched to.
        """
        self.logger.debug("tk-mari context changed to %s", str(new_context))

        if self.has_ui:
            # destroy the menu:
            self._menu_generator.destroy_menu()

        self.create_menu()
        self._run_app_instance_commands()

    def destroy_engine(self):
        """
        Called when the engine is being destroyed
        """
        self.log_debug("%s: Destroying..." % self)

        if self.has_ui:
            # destroy the menu:
            self._menu_generator.destroy_menu()

        # disconnect from Mari project events:
        mari.utils.disconnect(mari.projects.opened, self.__on_project_opened)
        # mari.utils.disconnect(mari.projects.saved, self.__on_project_saved)

    @property
    def has_ui(self):
        """
        Detect and return if mari is not running in terminal mode
        """
        return not mari.app.inTerminalMode()

    def create_menu(self):
        if self.has_ui:
            # create the Shotgun menu
            tk_mari = self.import_module("tk_mari")
            self._menu_generator = tk_mari.MenuGenerator(self)
            self._menu_generator.create_menu()

    #####################################################################################
    # Panel Support

    def show_panel(self, panel_id, title, bundle, widget_class, *args, **kwargs):
        """
        Shows a panel in Mari. If the panel already exists, the previous panel is swapped out
        and replaced with a new one. In this case, the contents of the panel (e.g. the toolkit app)
        is not destroyed but carried over to the new panel.

        If this is being called from a non-pane menu in Nuke, there isn't a well established logic
        for where the panel should be mounted. In this case, the code will look for suitable
        areas in the UI and try to panel it there, starting by looking for the property pane and
        trying to dock panels next to this.

        :param panel_id: Unique id to associate with the panel, as obtained by register_panel().
        :param title: The title of the window
        :param bundle: The app, engine or framework object that is associated with this window
        :param widget_class: The class of the UI to be constructed. This must derive from QWidget.

        Additional parameters specified will be passed through to the widget_class constructor.

        :returns: the created widget_class instance
        """
        mari_version = mari.app.version()
        if mari_version.major() < 4:
            raise AttributeError("This version of Mari ({}.{}v{}) may have palette resize issues. "
                                 "Skipping show_panel method.".format(mari_version.major(),
                                                                      mari_version.minor(),
                                                                      mari_version.revision()))

        from tank.platform.qt import QtCore, QtGui

        self.logger.debug("Showing pane %s - %s from %s", panel_id, title, bundle.name)

        # make a unique id for the app widget based off of the panel id
        widget_id = SHOTGUN_APP_PALETTE_PREFIX + panel_id

        # Get the panel widget and main window widget
        main_window = None
        shotgun_widget = None
        for widget in QtGui.QApplication.allWidgets():
            widget_name = widget.objectName()
            if widget_name == widget_id:
                shotgun_widget = widget
            elif widget_name == MARI_MAIN_WINDOW_WIDGET_NAME:
                main_window = widget

        if not main_window:
            raise Exception("Unable to get the '%s' widget!" % MARI_MAIN_WINDOW_WIDGET_NAME)

        # If the widget doesn't already exist, create it
        if not shotgun_widget:
            self.logger.debug("Creating new widget %s", widget_id)
            shotgun_widget = widget_class(*args, **kwargs)
        else:
            # Reparent the Shotgun app panel widget under Mari main window
            # to prevent it from being deleted with the existing Mari palette.
            self.logger.debug("Reparenting widget %s under Mari main window.", widget_id)

        shotgun_widget.setParent(main_window)

        # Now if the palette exists, remove it
        palette_widget = mari.palettes.find(panel_id)
        if palette_widget:
            mari.palettes.remove(palette_widget.name())

        # Now create the new palette
        palette_widget = mari.palettes.create(panel_id, shotgun_widget)

        # Set the palette's name (title)
        palette_widget.setShortName(title)

        # And show it
        palette_widget.showInFront()

        return shotgun_widget

    def find_geometry_for_publish(self, sg_publish):
        """
        Find the geometry and version info for the specified publish if it exists in the current project

        :param sg_publish:  The Shotgun publish to find geo for.  This is a Shotgun entity dictionary
                            containing at least the entity "type" and "id".
        :returns:           Tuple containing the geo and version that match the publish if found.
        """
        return self.__geometry_mgr.find_geometry_for_publish(sg_publish)

    def list_geometry(self):
        """
        Find all Shotgun aware geometry in the scene.  Any non-Shotgun aware geometry is ignored!

        :returns:   A list of dictionaries containing the geo together with any Shotgun info
                    that was found on it
        """
        return self.__geometry_mgr.list_geometry()

    def list_geometry_versions(self, geo):
        """
        Find all Shotgun aware versions for the specified geometry.  Any non-Shotgun aware versions are
        ignored!

        :param geo: The Mari GeoEntity to find all versions for
        :returns:   A list of dictionaries containing the geo_version together with any Shotgun info
                    that was found on it
        """
        return self.__geometry_mgr.list_geometry_versions(geo)

    def load_geometry(self, sg_publish, options=None, objects_to_load=None):
        """
        Wraps the Mari GeoManager.load() method and additionally tags newly loaded geometry with Shotgun
        specific metadata.  See Mari API documentation for more information on GeoManager.load().

        :param sg_publish:      The shotgun publish to load.  This should be a Shotgun entity dictionary
                                containing at least the entity "type" and "id".
        :param options:         [Mari arg] - Options to be passed to the file loader when loading the geometry
        :param objects_to_load: [Mari arg] - A list of objects to load from the file
        :returns:               A list of the loaded GeoEntity instances that were created
        """
        return self.__geometry_mgr.load_geometry(sg_publish, options, objects_to_load)

    def get_shotgun_info(self, mari_entity):
        """
        Get all Shotgun info stored with the specified mari entity.

        :param mari_entity: The mari entity to query metadata from.
        :returns:           Dictionary containing all Shotgun metadata found
                            in the Mari entity.
        """
        return self.__metadata_mgr.get_metadata(mari_entity)

    def set_project_version(self, mari_project, version):
        """
        Set the version metadata on a project

        :param mari_project:    The mari project entity to set the metadata on
        :param version:         The version string to set
        """
        self.__metadata_mgr.set_project_version(mari_project, version)

    def get_project_version(self, mari_project):
        """
        Get the version metadata for a project

        :param mari_project:    The mari project entity to retrieve the metadata from
        :returns:               A string representing the version number
        """
        return self.__metadata_mgr.get_project_version(mari_project)

    def add_geometry_version(self, geo, sg_publish, options=None):
        """
        Wraps the Mari GeoEntity.addVersion() method and additionally tags newly loaded geometry versions
        with Shotgun specific metadata. See Mari API documentation for more information on
        GeoEntity.addVersion().

        :param geo:             The Mari GeoEntity to add a version to
        :param sg_publish:      The publish to load as a new version.  This should be a Shotgun entity dictionary
                                containing at least the entity "type" and "id".
        :param options:         [Mari arg] - Options to be passed to the file loader when loading the geometry.  The
                                options will default to the options that were used to load the current version if
                                not specified.
        :returns:               The new GeoEntityVersion instance
        """
        return self.__geometry_mgr.add_geometry_version(geo, sg_publish, options)

    def create_project(self, name, sg_publishes, channels_to_create, channels_to_import=[],
                       project_meta_options=None, objects_to_load=None):
        """
        Wraps the Mari ProjectManager.create() method and additionally tags newly created project and all
        loaded geometry & versions with Shotgun specific metadata. See Mari API documentation for more
        information on ProjectManager.create().

        :param name:                    [Mari arg] - The name to use for the new project
        :param sg_publishes:            A list of publishes to load into the new project.  At least one publish
                                        must be specified!  Each entry in the list should be a Shotgun entity
                                        dictionary containing at least the entity "type" and "id".
        :param channels_to_create:      [Mari arg] - A list of channels to create for geometry in the new project
        :param channels_to_import:      [Mari arg] - A list of channels to import for geometry in the new project
        :param project_meta_options:    [Mari arg] - A dictionary of project creation meta options - these are
                                        typically the mesh options used when loading the geometry
        :param objects_to_load:         [Mari arg] - A list of objects to load from the files
        :returns:                       The newly created Project instance
        """
        return self.__project_mgr.create_project(name, sg_publishes, channels_to_create, channels_to_import,
                                       project_meta_options, objects_to_load)

    ##########################################################################################
    # Logging

    def _emit_log_message(self, handler, record):
        """
        Called by the engine to log messages in Maya script editor.
        All log messages from the toolkit logging namespace will be passed to this method.

        :param handler: Log handler that this message was dispatched from.
                        Its default format is "[levelname basename] message".
        :type handler: :class:`~python.logging.LogHandler`
        :param record: Standard python logging record.
        :type record: :class:`~python.logging.LogRecord`
        """
        # Give a standard format to the message:
        #     Shotgun <basename>: <message>
        # where "basename" is the leaf part of the logging record name,
        # for example "tk-multi-shotgunpanel" or "qt_importer".
        if record.levelno < logging.INFO:
            formatter = logging.Formatter("Debug: Shotgun %(basename)s: %(message)s")
        else:
            formatter = logging.Formatter("Shotgun %(basename)s: %(message)s")

        msg = formatter.format(record)

        # Select Mari output to use according to the logging record level.
        if record.levelno >= logging.ERROR:
            mari.utils.message(msg)

        # Send the message to the script editor.
        print msg

    def __on_project_opened(self, opened_project, is_new):
        """
        Called when a project is opened in Mari.  This looks for Toolkit metadata on the newly opened
        project and if it finds any, it tries to build a new context and restarts the engine with this
        new context.

        :param opened_project:  The mari Project instance for the newly opened project
        :param is_new:          True if the opened project is a new project
        """
        if is_new:
            # for now, do nothing with new projects.
            # TODO: should we tag project with metadata?
            return

        self.log_debug("Project opened - attempting to set the current Work Area to match...")

        # get the context for the project that's been opened
        # using the metadata stored on the project (if available):
        md = self.__metadata_mgr.get_project_metadata(opened_project)
        if not md:
            # This project has never been opened with Toolkit running before
            # so don't need to do anything!
            self.log_debug("Work area unchanged - the opened project is not Shotgun aware!")
            return

        # for backwards compatibility
        # set version of any project containing sgtk metadata, but no version to 1
        if not self.__metadata_mgr.get_project_version(opened_project):
            self.__metadata_mgr.set_project_version(opened_project, 1)

        # try to determine the project context from the metadata:
        ctx_entity = None
        if md.get("task_id"):
            ctx_entity = {"type":"Task", "id":md["task_id"]}
        elif md.get("entity_id") and md.get("entity_type"):
            ctx_entity = {"type":md["entity_type"], "id":md["entity_id"]}
        elif md.get("project_id"):
            ctx_entity = {"type":"Project", "id":md["project_id"]}
        else:
            # failed to determine the context for the project!
            self.log_debug("Work area unchanged - failed to determine a context for the opened project!")
            return

        # get the context from the context entity:
        ctx = None
        try:
            ctx = self.sgtk.context_from_entity(ctx_entity["type"], ctx_entity["id"])
        except TankError, e:
            self.log_error("Work area unchanged - Failed to create context from '%s %s': %s"
                           % (ctx_entity["type"], ctx_entity["id"], e))
            return

        if ctx == self.context:
            # nothing to do - context is the same!
            return

        self.log_debug("Changing the engine context to Work Area: %s" % ctx)

        # change current engine context:
        sgtk.platform.change_context(ctx)

    def __on_project_saved(self, saved_project):
        if not self.__metadata_mgr.get_metadata(saved_project):
            # this is not an sgtk compliant project
            return

        workfiles_app = self.apps.get("tk-multi-workfiles2")
        proj_mgr_app = self.apps.get("tk-mari-projectmanager")
        if not workfiles_app or not proj_mgr_app:
            self.log_error("Unable to find workfiles or projectmanager app. Not exporting msf file.")
            return

        fields = self.context.as_template_fields()

        # use project name to obtain "name" field
        project_name_template = proj_mgr_app.get_template("template_new_project_name")
        if not project_name_template.validate(saved_project.name()):
            # this is not an sgtk compliant project
            return
        fields.update(project_name_template.get_fields(saved_project.name()))

        # use project metadata to get the "version" field
        fields["version"] = self.__metadata_mgr.get_project_version(saved_project)

        work_template = workfiles_app.get_template("template_work")
        work_file_path = work_template.apply_fields(fields)

        self.log_debug("Exporting mari session file to: %s" % work_file_path)
        mari.session.exportSession(work_file_path)

    def _run_app_instance_commands(self):
        """
        Runs the series of app instance commands listed in the 'run_at_startup' setting
        of the environment configuration yaml file.
        """

        # Build a dictionary mapping app instance names to dictionaries of commands they registered with the engine.
        app_instance_commands = {}
        for (command_name, value) in self.commands.iteritems():
            app_instance = value["properties"].get("app")
            if app_instance:
                # Add entry 'command name: command function' to the command dictionary of this app instance.
                command_dict = app_instance_commands.setdefault(app_instance.instance_name, {})
                command_dict[command_name] = value["callback"]

        commands_to_run = []
        # Run the series of app instance commands listed in the 'run_at_startup' setting.
        for app_setting_dict in self.get_setting("run_at_startup", []):

            app_instance_name = app_setting_dict["app_instance"]
            # Menu name of the command to run or '' to run all commands of the given app instance.
            setting_command_name = app_setting_dict["name"]

            # Retrieve the command dictionary of the given app instance.
            command_dict = app_instance_commands.get(app_instance_name)

            if command_dict is None:
                self.logger.warning(
                    "%s configuration setting 'run_at_startup' requests app '%s' that is not installed.",
                    self.name, app_instance_name)
            else:
                if not setting_command_name:
                    # Run all commands of the given app instance.
                    # Run these commands once Maya will have completed its UI update and be idle
                    # in order to run them after the ones that restore the persisted Shotgun app panels.
                    for (command_name, command_function) in command_dict.iteritems():
                        self.logger.debug("%s startup running app '%s' command '%s'.",
                                       self.name, app_instance_name, command_name)
                        commands_to_run.append(command_function)
                else:
                    # Run the command whose name is listed in the 'run_at_startup' setting.
                    # Run this command once Maya will have completed its UI update and be idle
                    # in order to run it after the ones that restore the persisted Shotgun app panels.
                    command_function = command_dict.get(setting_command_name)
                    if command_function:
                        self.logger.debug("%s startup running app '%s' command '%s'.",
                                       self.name, app_instance_name, setting_command_name)
                        commands_to_run.append(command_function)
                    else:
                        known_commands = ', '.join("'%s'" % name for name in command_dict)
                        self.logger.warning(
                            "%s configuration setting 'run_at_startup' requests app '%s' unknown command '%s'. "
                            "Known commands: %s",
                            self.name, app_instance_name, setting_command_name, known_commands)

        # Run the commands once Mari will have completed its UI update and be idle
        # in order to run it after the ones that restore the persisted Shotgun app panels.
        # Set the _callback_from_non_pane_menu hint so that the show_panel method knows this
        # was invoked not from the pane menu.
        for command in commands_to_run:
            command()
