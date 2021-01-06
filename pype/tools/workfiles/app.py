import sys
import os
import copy
import getpass
import shutil
import logging

import Qt
from Qt import QtWidgets, QtCore
from avalon import style, io, api, pipeline

from avalon.tools import lib as tools_lib
from avalon.tools.widgets import AssetWidget
from avalon.tools.models import TasksModel
from avalon.tools.delegates import PrettyTimeDelegate

from .model import FilesModel
from .view import FilesView

from pype.lib import (
    Anatomy,
    get_workdir
)

log = logging.getLogger(__name__)

module = sys.modules[__name__]
module.window = None


class NameWindow(QtWidgets.QDialog):
    """Name Window to define a unique filename inside a root folder

    The filename will be based on the "workfile" template defined in the
    project["config"]["template"].

    """

    def __init__(self, parent, root, anatomy, template_key, session=None):
        super(NameWindow, self).__init__(parent=parent)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.FramelessWindowHint)

        self.result = None
        self.host = api.registered_host()
        self.root = root
        self.work_file = None

        if not session:
            # Fallback to active session
            session = api.Session

        # Set work file data for template formatting
        asset_name = session["AVALON_ASSET"]
        project_doc = io.find_one({
            "type": "project"
        })
        self.data = {
            "project": {
                "name": project_doc["name"],
                "code": project_doc["data"].get("code")
            },
            "asset": asset_name,
            "task": session["AVALON_TASK"],
            "version": 1,
            "user": getpass.getuser(),
            "comment": "",
            "ext": None
        }

        # Store project anatomy
        self.anatomy = anatomy
        self.template = anatomy.templates[template_key]["file"]
        self.template_key = template_key

        # Btns widget
        btns_widget = QtWidgets.QWidget(self)

        btn_ok = QtWidgets.QPushButton("Ok", btns_widget)
        btn_cancel = QtWidgets.QPushButton("Cancel", btns_widget)

        btns_layout = QtWidgets.QHBoxLayout(btns_widget)
        btns_layout.addWidget(btn_ok)
        btns_layout.addWidget(btn_cancel)

        # Inputs widget
        inputs_widget = QtWidgets.QWidget(self)

        # Version widget
        version_widget = QtWidgets.QWidget(inputs_widget)

        # Version number input
        version_input = QtWidgets.QSpinBox(version_widget)
        version_input.setMinimum(1)
        version_input.setMaximum(9999)

        # Last version checkbox
        last_version_check = QtWidgets.QCheckBox(
            "Next Available Version", version_widget
        )
        last_version_check.setChecked(True)

        version_layout = QtWidgets.QHBoxLayout(version_widget)
        version_layout.setContentsMargins(0, 0, 0, 0)
        version_layout.addWidget(version_input)
        version_layout.addWidget(last_version_check)

        # Preview widget
        preview_label = QtWidgets.QLabel("Preview filename", inputs_widget)

        # Subversion input
        subversion_input = QtWidgets.QLineEdit(inputs_widget)
        subversion_input.setPlaceholderText("Will be part of filename.")

        # Extensions combobox
        ext_combo = QtWidgets.QComboBox(inputs_widget)
        ext_combo.addItems(self.host.file_extensions())

        # Build inputs
        inputs_layout = QtWidgets.QFormLayout(inputs_widget)
        # Add version only if template contain version key
        # - since the version can be padded with "{version:0>4}" we only search
        #   for "{version".
        if "{version" in self.template:
            inputs_layout.addRow("Version:", version_widget)

        # Add subversion only if template containt `{comment}`
        if "{comment}" in self.template:
            inputs_layout.addRow("Subversion:", subversion_input)
        inputs_layout.addRow("Extension:", ext_combo)
        inputs_layout.addRow("Preview:", preview_label)

        # Build layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(inputs_widget)
        main_layout.addWidget(btns_widget)

        # Singal callback registration
        version_input.valueChanged.connect(self.on_version_spinbox_changed)
        last_version_check.stateChanged.connect(
            self.on_version_checkbox_changed
        )

        subversion_input.textChanged.connect(self.on_comment_changed)
        ext_combo.currentIndexChanged.connect(self.on_extension_changed)

        btn_ok.pressed.connect(self.on_ok_pressed)
        btn_cancel.pressed.connect(self.on_cancel_pressed)

        # Allow "Enter" key to accept the save.
        btn_ok.setDefault(True)

        # Force default focus to comment, some hosts didn't automatically
        # apply focus to this line edit (e.g. Houdini)
        subversion_input.setFocus()

        # Store widgets
        self.btn_ok = btn_ok

        self.version_widget = version_widget

        self.version_input = version_input
        self.last_version_check = last_version_check

        self.preview_label = preview_label
        self.subversion_input = subversion_input
        self.ext_combo = ext_combo

        self.refresh()

    def on_version_spinbox_changed(self, value):
        self.data["version"] = value
        self.refresh()

    def on_version_checkbox_changed(self, _value):
        self.refresh()

    def on_comment_changed(self, text):
        self.data["comment"] = text
        self.refresh()

    def on_extension_changed(self):
        ext = self.ext_combo.currentText()
        if ext == self.data["ext"]:
            return
        self.data["ext"] = ext
        self.refresh()

    def on_ok_pressed(self):
        self.result = self.work_file
        self.close()

    def on_cancel_pressed(self):
        self.close()

    def get_result(self):
        return self.result

    def get_work_file(self):
        data = copy.deepcopy(self.data)
        if not data["comment"]:
            data.pop("comment", None)

        anatomy_filled = self.anatomy.format(data)
        return anatomy_filled[self.template_key]["file"]

    def refresh(self):
        extensions = self.host.file_extensions()
        extension = self.data["ext"]
        if extension is None:
            # Define saving file extension
            current_file = self.host.current_file()
            if current_file:
                # Match the extension of current file
                _, extension = os.path.splitext(current_file)
            else:
                extension = extensions[0]

        if extension != self.data["ext"]:
            self.data["ext"] = extension
            index = self.ext_combo.findText(
                extension, QtCore.Qt.MatchFixedString
            )
            if index >= 0:
                self.ext_combo.setCurrentIndex(index)

        if not self.last_version_check.isChecked():
            self.version_input.setEnabled(True)
            self.data["version"] = self.version_input.value()

            work_file = self.get_work_file()

        else:
            self.version_input.setEnabled(False)

            data = copy.deepcopy(self.data)
            template = str(self.template)

            if not data["comment"]:
                data.pop("comment", None)

            version = api.last_workfile_with_version(
                self.root, template, data, extensions
            )[1]

            if version is None:
                version = 1
            else:
                version += 1

            found_valid_version = False
            # Check if next version is valid version and give a chance to try
            # next 100 versions
            for idx in range(100):
                # Store version to data
                self.data["version"] = version

                work_file = self.get_work_file()
                # Safety check
                path = os.path.join(self.root, work_file)
                if not os.path.exists(path):
                    found_valid_version = True
                    break

                # Try next version
                version += 1
                # Log warning
                if idx == 0:
                    log.warning((
                        "BUG: Function `last_workfile_with_version` "
                        "didn't return last version."
                    ))
            # Raise exception if even 100 version fallback didn't help
            if not found_valid_version:
                raise AssertionError(
                    "This is a bug. Couldn't find valid version!"
                )

        self.work_file = work_file

        path_exists = os.path.exists(os.path.join(self.root, work_file))

        self.btn_ok.setEnabled(not path_exists)

        if path_exists:
            self.preview_label.setText(
                "<font color='red'>Cannot create \"{0}\" because file exists!"
                "</font>".format(work_file)
            )
        else:
            self.preview_label.setText(
                "<font color='green'>{0}</font>".format(work_file)
            )


class TasksWidget(QtWidgets.QWidget):
    """Widget showing active Tasks"""

    task_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super(TasksWidget, self).__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)

        view = QtWidgets.QTreeView()
        view.setIndentation(0)
        model = TasksModel(io)
        view.setModel(model)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(view)

        # Hide the default tasks "count" as we don't need that data here.
        view.setColumnHidden(1, True)

        selection = view.selectionModel()
        selection.currentChanged.connect(self.task_changed)

        self.models = {
            "tasks": model
        }

        self.widgets = {
            "view": view,
        }

        self._last_selected_task = None

    def set_asset(self, asset):
        if asset is None:
            # Asset deselected
            return

        # Try and preserve the last selected task and reselect it
        # after switching assets. If there's no currently selected
        # asset keep whatever the "last selected" was prior to it.
        current = self.get_current_task()
        if current:
            self._last_selected_task = current

        self.models["tasks"].set_assets(asset_docs=[asset])

        if self._last_selected_task:
            self.select_task(self._last_selected_task)

        # Force a task changed emit.
        self.task_changed.emit()

    def select_task(self, task):
        """Select a task by name.

        If the task does not exist in the current model then selection is only
        cleared.

        Args:
            task (str): Name of the task to select.

        """

        # Clear selection
        view = self.widgets["view"]
        model = view.model()
        selection_model = view.selectionModel()
        selection_model.clearSelection()

        # Select the task
        mode = selection_model.Select | selection_model.Rows
        for row in range(model.rowCount(QtCore.QModelIndex())):
            index = model.index(row, 0, QtCore.QModelIndex())
            name = index.data(QtCore.Qt.DisplayRole)
            if name == task:
                selection_model.select(index, mode)

                # Set the currently active index
                view.setCurrentIndex(index)

    def get_current_task(self):
        """Return name of task at current index (selected)

        Returns:
            str: Name of the current task.

        """
        view = self.widgets["view"]
        index = view.currentIndex()
        index = index.sibling(index.row(), 0)  # ensure column zero for name

        selection = view.selectionModel()
        if selection.isSelected(index):
            # Ignore when the current task is not selected as the "No task"
            # placeholder might be the current index even though it's
            # disallowed to be selected. So we only return if it is selected.
            return index.data(QtCore.Qt.DisplayRole)


class FilesWidget(QtWidgets.QWidget):
    """A widget displaying files that allows to save and open files."""
    def __init__(self, parent=None):
        super(FilesWidget, self).__init__(parent=parent)

        # Setup
        self._asset = None
        self._task = None

        # Pype's anatomy object for current project
        self.anatomy = Anatomy(io.Session["AVALON_PROJECT"])
        # Template key used to get work template from anatomy templates
        # TODO change template key based on task
        self.template_key = "work"

        # Do not set root with Anatomy's roots because it would break host's
        # implementation of `work_root` function
        self.root = None
        self.host = api.registered_host()

        # Whether to automatically select the latest modified
        # file on a refresh of the files model.
        self.auto_select_latest_modified = True

        # Avoid crash in Blender and store the message box
        # (setting parent doesn't work as it hides the message box)
        self._messagebox = None

        widgets = {
            "filter": QtWidgets.QLineEdit(),
            "list": FilesView(),
            "open": QtWidgets.QPushButton("Open"),
            "browse": QtWidgets.QPushButton("Browse"),
            "save": QtWidgets.QPushButton("Save As")
        }

        delegates = {
            "time": PrettyTimeDelegate()
        }

        # Create the files model
        extensions = set(self.host.file_extensions())
        self.model = FilesModel(file_extensions=extensions)
        self.proxy = QtCore.QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setDynamicSortFilter(True)
        self.proxy.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)

        # Set up the file list tree view
        widgets["list"].setModel(self.proxy)
        widgets["list"].setSortingEnabled(True)
        widgets["list"].setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        # Date modified delegate
        widgets["list"].setItemDelegateForColumn(1, delegates["time"])
        widgets["list"].setIndentation(3)   # smaller indentation

        # Default to a wider first filename column it is what we mostly care
        # about and the date modified is relatively small anyway.
        widgets["list"].setColumnWidth(0, 330)

        widgets["filter"].textChanged.connect(self.proxy.setFilterFixedString)
        widgets["filter"].setPlaceholderText("Filter files..")

        # Home Page
        # Build buttons widget for files widget
        buttons = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(buttons)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widgets["open"])
        layout.addWidget(widgets["browse"])
        layout.addWidget(widgets["save"])

        # Build files widgets for home page
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widgets["filter"])
        layout.addWidget(widgets["list"])
        layout.addWidget(buttons)

        widgets["list"].doubleClickedLeft.connect(self.on_open_pressed)
        widgets["list"].customContextMenuRequested.connect(
            self.on_context_menu
        )
        widgets["open"].pressed.connect(self.on_open_pressed)
        widgets["browse"].pressed.connect(self.on_browse_pressed)
        widgets["save"].pressed.connect(self.on_save_as_pressed)

        self.widgets = widgets
        self.delegates = delegates

    def set_asset_task(self, asset, task):
        self._asset = asset
        self._task = task

        # Define a custom session so we can query the work root
        # for a "Work area" that is not our current Session.
        # This way we can browse it even before we enter it.
        if self._asset and self._task:
            session = self._get_session()
            self.root = self.host.work_root(session)

            exists = os.path.exists(self.root)
            self.widgets["browse"].setEnabled(exists)
            self.widgets["open"].setEnabled(exists)
            self.model.set_root(self.root)
        else:
            self.model.set_root(None)

    def _get_session(self):
        """Return a modified session for the current asset and task"""

        session = api.Session.copy()
        changes = pipeline.compute_session_changes(
            session,
            asset=self._asset,
            task=self._task
        )
        session.update(changes)

        return session

    def _enter_session(self):
        """Enter the asset and task session currently selected"""

        session = api.Session.copy()
        changes = pipeline.compute_session_changes(
            session,
            asset=self._asset,
            task=self._task
        )
        if not changes:
            # Return early if we're already in the right Session context
            # to avoid any unwanted Task Changed callbacks to be triggered.
            return

        api.update_current_task(asset=self._asset, task=self._task)

    def open_file(self, filepath):
        host = self.host
        if host.has_unsaved_changes():
            result = self.save_changes_prompt()
            if result is None:
                # Cancel operation
                return False

            # Save first if has changes
            if result:
                current_file = host.current_file()
                if not current_file:
                    # If the user requested to save the current scene
                    # we can't actually automatically do so if the current
                    # file has not been saved with a name yet. So we'll have
                    # to opt out.
                    log.error("Can't save scene with no filename. Please "
                              "first save your work file using 'Save As'.")
                    return

                # Save current scene, continue to open file
                host.save_file(current_file)

        self._enter_session()
        host.open_file(filepath)
        self.window().close()

    def save_changes_prompt(self):
        self._messagebox = messagebox = QtWidgets.QMessageBox()

        messagebox.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        messagebox.setIcon(messagebox.Warning)
        messagebox.setWindowTitle("Unsaved Changes!")
        messagebox.setText(
            "There are unsaved changes to the current file."
            "\nDo you want to save the changes?"
        )
        messagebox.setStandardButtons(
            messagebox.Yes | messagebox.No | messagebox.Cancel
        )

        # Parenting the QMessageBox to the Widget seems to crash
        # so we skip parenting and explicitly apply the stylesheet.
        messagebox.setStyleSheet(style.load_stylesheet())

        result = messagebox.exec_()
        if result == messagebox.Yes:
            return True
        elif result == messagebox.No:
            return False
        return None

    def get_filename(self):
        """Show save dialog to define filename for save or duplicate

        Returns:
            str: The filename to create.

        """
        session = self._get_session()

        window = NameWindow(
            parent=self,
            root=self.root,
            anatomy=self.anatomy,
            template_key=self.template_key,
            session=session
        )
        window.exec_()

        return window.get_result()

    def on_duplicate_pressed(self):
        work_file = self.get_filename()
        if not work_file:
            return

        src = self._get_selected_filepath()
        dst = os.path.join(self.root, work_file)
        shutil.copy(src, dst)

        self.refresh()

    def _get_selected_filepath(self):
        """Return current filepath selected in view"""
        model = self.model
        view = self.widgets["list"]
        selection = view.selectionModel()
        index = selection.currentIndex()
        if not index.isValid():
            return

        return index.data(model.FilePathRole)

    def on_open_pressed(self):
        path = self._get_selected_filepath()
        if not path:
            print("No file selected to open..")
            return

        self.open_file(path)

    def on_browse_pressed(self):
        ext_filter = "Work File (*{0})".format(
            " *".join(self.host.file_extensions())
        )
        kwargs = {
            "caption": "Work Files",
            "filter": ext_filter
        }
        if Qt.__binding__ in ("PySide", "PySide2"):
            kwargs["dir"] = self.root
        else:
            kwargs["directory"] = self.root

        work_file = QtWidgets.QFileDialog.getOpenFileName(**kwargs)[0]
        if work_file:
            self.open_file(work_file)

    def on_save_as_pressed(self):
        work_file = self.get_filename()
        if not work_file:
            return

        # Initialize work directory if it has not been initialized before
        if not os.path.exists(self.root):
            log.debug("Initializing Work Directory: %s", self.root)
            self.initialize_work_directory()
            if not os.path.exists(self.root):
                # Failed to initialize Work Directory
                log.error(
                    "Failed to initialize Work Directory: {}".format(self.root)
                )
                return

        file_path = os.path.join(self.root, work_file)

        self._enter_session()   # Make sure we are in the right session
        self.host.save_file(file_path)
        self.set_asset_task(self._asset, self._task)
        self.refresh()

    def initialize_work_directory(self):
        """Initialize Work Directory.

        This is used when the Work Directory does not exist yet.

        This finds the current AVALON_APP_NAME and tries to triggers its
        `.toml` initialization step. Note that this will only be valid
        whenever `AVALON_APP_NAME` is actually set in the current session.

        """

        # Inputs (from the switched session and running app)
        session = api.Session.copy()
        changes = pipeline.compute_session_changes(
            session,
            asset=self._asset,
            task=self._task
        )
        session.update(changes)

        # Prepare documents to get workdir data
        project_doc = io.find_one({"type": "project"})
        asset_doc = io.find_one(
            {
                "type": "asset",
                "name": session["AVALON_ASSET"]
            }
        )
        task_name = session["AVALON_TASK"]
        host_name = session["AVALON_APP"]

        # Get workdir from collected documents
        workdir = get_workdir(project_doc, asset_doc, task_name, host_name)
        # Create workdir if does not exist yet
        if not os.path.exists(workdir):
            os.makedirs(workdir)

        # Force a full to the asset as opposed to just self.refresh() so
        # that it will actually check again whether the Work directory exists
        self.set_asset_task(self._asset, self._task)

    def refresh(self):
        """Refresh listed files for current selection in the interface"""
        self.model.refresh()

        if self.auto_select_latest_modified:
            tools_lib.schedule(self._select_last_modified_file, 100)

    def on_context_menu(self, point):
        view = self.widgets["list"]
        index = view.indexAt(point)
        if not index.isValid():
            return

        is_enabled = index.data(FilesModel.IsEnabled)
        if not is_enabled:
            return

        menu = QtWidgets.QMenu(self)

        # Duplicate
        action = QtWidgets.QAction("Duplicate", menu)
        tip = "Duplicate selected file."
        action.setToolTip(tip)
        action.setStatusTip(tip)
        action.triggered.connect(self.on_duplicate_pressed)
        menu.addAction(action)

        # Show the context action menu
        global_point = view.mapToGlobal(point)
        action = menu.exec_(global_point)
        if not action:
            return

    def _select_last_modified_file(self):
        """Utility function to select the file with latest date modified"""
        role = self.model.DateModifiedRole
        view = self.widgets["list"]
        model = view.model()

        highest_index = None
        highest = 0
        for row in range(model.rowCount()):
            index = model.index(row, 0, parent=QtCore.QModelIndex())
            if not index.isValid():
                continue

            modified = index.data(role)
            if modified is not None and modified > highest:
                highest_index = index
                highest = modified

        if highest_index:
            view.setCurrentIndex(highest_index)


class Window(QtWidgets.QMainWindow):
    """Work Files Window"""
    title = "Work Files"

    def __init__(self, parent=None):
        super(Window, self).__init__(parent=parent)
        self.setWindowTitle(self.title)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowCloseButtonHint)

        pages = {
            "home": QtWidgets.QWidget()
        }

        widgets = {
            "pages": QtWidgets.QStackedWidget(),
            "body": QtWidgets.QWidget(),
            "assets": AssetWidget(io),
            "tasks": TasksWidget(),
            "files": FilesWidget()
        }

        self.setCentralWidget(widgets["pages"])
        widgets["pages"].addWidget(pages["home"])

        # Build home
        layout = QtWidgets.QVBoxLayout(pages["home"])
        layout.addWidget(widgets["body"])

        # Build home - body
        layout = QtWidgets.QVBoxLayout(widgets["body"])
        split = QtWidgets.QSplitter()
        split.addWidget(widgets["assets"])
        split.addWidget(widgets["tasks"])
        split.addWidget(widgets["files"])
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 3)
        layout.addWidget(split)

        # Add top margin for tasks to align it visually with files as
        # the files widget has a filter field which tasks does not.
        widgets["tasks"].setContentsMargins(0, 32, 0, 0)

        # Connect signals
        widgets["assets"].current_changed.connect(self.on_asset_changed)
        widgets["tasks"].task_changed.connect(self.on_task_changed)

        self.widgets = widgets
        self.refresh()

        # Force focus on the open button by default, required for Houdini.
        self.widgets["files"].widgets["open"].setFocus()

        self.resize(900, 600)

    def keyPressEvent(self, event):
        """Custom keyPressEvent.

        Override keyPressEvent to do nothing so that Maya's panels won't
        take focus when pressing "SHIFT" whilst mouse is over viewport or
        outliner. This way users don't accidently perform Maya commands
        whilst trying to name an instance.

        """

    def on_task_changed(self):
        # Since we query the disk give it slightly more delay
        tools_lib.schedule(self._on_task_changed, 100, channel="mongo")

    def on_asset_changed(self):
        tools_lib.schedule(self._on_asset_changed, 50, channel="mongo")

    def set_context(self, context):
        if "asset" in context:
            asset = context["asset"]
            asset_document = io.find_one(
                {
                    "name": asset,
                    "type": "asset"
                },
                {
                    "data.tasks": 1
                }
            )

            # Select the asset
            self.widgets["assets"].select_assets([asset], expand=True)

            # Force a refresh on Tasks?
            self.widgets["tasks"].set_asset(asset_document)

        if "task" in context:
            self.widgets["tasks"].select_task(context["task"])

    def refresh(self):
        # Refresh asset widget
        self.widgets["assets"].refresh()

        self._on_task_changed()

    def _on_asset_changed(self):
        asset = self.widgets["assets"].get_selected_assets() or None

        if not asset:
            # Force disable the other widgets if no
            # active selection
            self.widgets["tasks"].setEnabled(False)
            self.widgets["files"].setEnabled(False)
        else:
            asset = asset[0]
            self.widgets["tasks"].setEnabled(True)

        self.widgets["tasks"].set_asset(asset)

    def _on_task_changed(self):
        asset = self.widgets["assets"].get_selected_assets() or None
        if asset is not None:
            asset = asset[0]
        task = self.widgets["tasks"].get_current_task()

        self.widgets["tasks"].setEnabled(bool(asset))
        self.widgets["files"].setEnabled(all([bool(task), bool(asset)]))

        files = self.widgets["files"]
        files.set_asset_task(asset, task)
        files.refresh()


def validate_host_requirements(host):
    if host is None:
        raise RuntimeError("No registered host.")

    # Verify the host has implemented the api for Work Files
    required = [
        "open_file",
        "save_file",
        "current_file",
        "has_unsaved_changes",
        "work_root",
        "file_extensions",
    ]
    missing = []
    for name in required:
        if not hasattr(host, name):
            missing.append(name)
    if missing:
        raise RuntimeError(
            "Host is missing required Work Files interfaces: "
            "%s (host: %s)" % (", ".join(missing), host)
        )
    return True


def show(root=None, debug=False, parent=None, use_context=True, save=True):
    """Show Work Files GUI"""
    # todo: remove `root` argument to show()

    try:
        module.window.close()
        del(module.window)
    except (AttributeError, RuntimeError):
        pass

    host = api.registered_host()
    validate_host_requirements(host)

    if debug:
        api.Session["AVALON_ASSET"] = "Mock"
        api.Session["AVALON_TASK"] = "Testing"

    with tools_lib.application():

        window = Window(parent=parent)
        window.refresh()

        if use_context:
            context = {"asset": api.Session["AVALON_ASSET"],
                       "silo": api.Session["AVALON_SILO"],
                       "task": api.Session["AVALON_TASK"]}
            window.set_context(context)

        window.widgets["files"].widgets["save"].setEnabled(save)

        window.show()
        window.setStyleSheet(style.load_stylesheet())

        module.window = window

        # Pull window to the front.
        module.window.raise_()
        module.window.activateWindow()
