from Qt import QtWidgets, QtCore, QtGui
from Qt.QtCore import Qt
from pype.tools.settings.settings.widgets.base import ProjectListWidget
import attr
import os
from pype.tools.settings.settings import style
from avalon.tools.delegates import PrettyTimeDelegate, pretty_timestamp

from pype.lib import PypeLogger

import json

log = PypeLogger().get_logger("SyncServer")

STATUS = {
    0: 'Queued',
    1: 'Failed',
    2: 'In Progress',
    3: 'Paused',
    4: 'Synced OK',
    -1: 'Not available'
}


class SyncServerWindow(QtWidgets.QDialog):
    """
        Main window that contains list of synchronizable projects and summary
        view with all synchronizable representations for first project
    """
    def __init__(self, sync_server, parent=None):
        super(SyncServerWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        self.setStyleSheet(style.load_stylesheet())
        self.setWindowIcon(QtGui.QIcon(style.app_icon_path()))
        self.resize(1400, 800)

        body = QtWidgets.QWidget(self)
        footer = QtWidgets.QWidget(self)
        footer.setFixedHeight(20)

        container = QtWidgets.QWidget()
        projects = SyncProjectListWidget(sync_server, self)
        projects.refresh()  # force selection of default
        repres = SyncRepresentationWidget(sync_server,
                                          project=projects.current_project,
                                          parent=self)

        container_layout = QtWidgets.QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        split = QtWidgets.QSplitter()
        split.addWidget(projects)
        split.addWidget(repres)
        split.setSizes([180, 950, 200])
        container_layout.addWidget(split)

        container.setLayout(container_layout)

        body_layout = QtWidgets.QHBoxLayout(body)
        body_layout.addWidget(container)
        body_layout.setContentsMargins(0, 0, 0, 0)

        message = QtWidgets.QLabel(footer)
        message.hide()

        footer_layout = QtWidgets.QVBoxLayout(footer)
        footer_layout.addWidget(message)
        footer_layout.setContentsMargins(0, 0, 0, 0)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(body)
        layout.addWidget(footer)

        self.setLayout(body_layout)
        self.setWindowTitle("Sync Server")

        projects.project_changed.connect(
            lambda: repres.table_view.model().set_project(
                projects.current_project))


class SyncProjectListWidget(ProjectListWidget):
    """
        Lists all projects that are synchronized to choose from
    """
    def __init__(self, sync_server, parent):
        super(SyncProjectListWidget, self).__init__(parent)
        self.sync_server = sync_server

    def validate_context_change(self):
        return True

    def refresh(self):
        model = self.project_list.model()
        model.clear()

        for project_name in self.sync_server.get_synced_presets().keys():
            model.appendRow(QtGui.QStandardItem(project_name))

        if len(self.sync_server.get_synced_presets().keys()) == 0:
            model.appendRow(QtGui.QStandardItem("No project configured"))

        self.current_project = self.project_list.currentIndex().data(
            QtCore.Qt.DisplayRole
        )
        if not self.current_project:
            self.current_project = self.project_list.model().item(0).\
                data(QtCore.Qt.DisplayRole)


class SyncRepresentationWidget(QtWidgets.QWidget):
    """
        Summary dialog with list of representations that matches current
        settings 'local_site' and 'remote_site'.
    """
    active_changed = QtCore.Signal()    # active index changed

    default_widths = (
        ("asset", 210),
        ("subset", 190),
        ("version", 10),
        ("representation", 90),
        ("created_dt", 100),
        ("sync_dt", 100),
        ("local_site", 60),
        ("remote_site", 70),
        ("files_count", 70),
        ("files_size", 70),
        ("priority", 20),
        ("state", 50)
    )

    def __init__(self, sync_server, project=None, parent=None):
        super(SyncRepresentationWidget, self).__init__(parent)

        self.sync_server = sync_server

        self._selected_id = None  # keep last selected _id

        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("Filter representations..")

        top_bar_layout = QtWidgets.QHBoxLayout()
        top_bar_layout.addWidget(self.filter)

        self.table_view = QtWidgets.QTableView()
        headers = [item[0] for item in self.default_widths]

        model = SyncRepresentationModel(sync_server, headers, project)
        self.table_view.setModel(model)
        self.table_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table_view.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self.table_view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.table_view.horizontalHeader().setSortIndicator(
            -1, Qt.AscendingOrder)
        self.table_view.setSortingEnabled(True)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().hide()

        time_delegate = PrettyTimeDelegate(self)
        column = self.table_view.model().get_header_index("created_dt")
        self.table_view.setItemDelegateForColumn(column, time_delegate)
        column = self.table_view.model().get_header_index("sync_dt")
        self.table_view.setItemDelegateForColumn(column, time_delegate)

        column = self.table_view.model().get_header_index("local_site")
        delegate = ImageDelegate(self)
        self.table_view.setItemDelegateForColumn(column, delegate)

        column = self.table_view.model().get_header_index("remote_site")
        delegate = ImageDelegate(self)
        self.table_view.setItemDelegateForColumn(column, delegate)

        column = self.table_view.model().get_header_index("files_size")
        delegate = SizeDelegate(self)
        self.table_view.setItemDelegateForColumn(column, delegate)

        for column_name, width in self.default_widths:
            idx = model.get_header_index(column_name)
            self.table_view.setColumnWidth(idx, width)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top_bar_layout)
        layout.addWidget(self.table_view)

        self.table_view.doubleClicked.connect(self._double_clicked)
        self.filter.textChanged.connect(lambda: model.set_filter(
            self.filter.text()))
        self.table_view.customContextMenuRequested.connect(
            self._on_context_menu)

        self.table_view.model().modelReset.connect(self._set_selection)

        self.selection_model = self.table_view.selectionModel()
        self.selection_model.selectionChanged.connect(self._selection_changed)

    def _selection_changed(self, new_selection):
        index = self.selection_model.currentIndex()
        self._selected_id = self.table_view.model().data(index, Qt.UserRole)

    def _set_selection(self):
        """
            Sets selection to 'self._selected_id' if exists.

            Keep selection during model refresh.
        """
        if self._selected_id:
            index = self.table_view.model().get_index(self._selected_id)
            if index and index.isValid():
                mode = QtCore.QItemSelectionModel.Select | \
                       QtCore.QItemSelectionModel.Rows
                self.selection_model.setCurrentIndex(index, mode)
            else:
                self._selected_id = None

    def _double_clicked(self, index):
        """
            Opens representation dialog with all files after doubleclick
        """
        _id = self.table_view.model().data(index, Qt.UserRole)
        detail_window = SyncServerDetailWindow(self.sync_server, _id,
            self.table_view.model()._project)
        detail_window.exec()

    def _on_context_menu(self, point):
        """
            Shows menu with loader actions on Right-click.
        """
        point_index = self.table_view.indexAt(point)
        if not point_index.isValid():
            return


class SyncRepresentationModel(QtCore.QAbstractTableModel):
    PAGE_SIZE = 19
    REFRESH_SEC = 5000
    DEFAULT_SORT = {
        "updated_dt_remote": -1,
        "_id": 1
    }
    SORT_BY_COLUMN = [
        "context.asset",            # asset
        "context.subset",           # subset
        "context.version",          # version
        "context.representation",   # representation
        "updated_dt_local",         # local created_dt
        "updated_dt_remote",        # remote created_dt
        "avg_progress_local",       # local progress
        "avg_progress_remote",      # remote progress
        "files_count",              # count of files
        "files_size",               # file size of all files
        "context.asset",            # priority TODO
        "status"                    # state
    ]

    numberPopulated = QtCore.Signal(int)

    @attr.s
    class SyncRepresentation:
        """
            Auxiliary object for easier handling.

            Fields must contain all header values (+ any arbitrary values).
        """
        _id = attr.ib()
        asset = attr.ib()
        subset = attr.ib()
        version = attr.ib()
        representation = attr.ib()
        created_dt = attr.ib(default=None)
        sync_dt = attr.ib(default=None)
        local_site = attr.ib(default=None)
        remote_site = attr.ib(default=None)
        files_count = attr.ib(default=None)
        files_size = attr.ib(default=None)
        priority = attr.ib(default=None)
        state = attr.ib(default=None)

    def __init__(self, sync_server, header, project=None):
        super(SyncRepresentationModel, self).__init__()
        self._header = header
        self._data = []
        self._project = project
        self._rec_loaded = 0
        self._buffer = []  # stash one page worth of records (actually cursor)
        self.filter = None

        self._initialized = False

        self.sync_server = sync_server
        # TODO think about admin mode
        # this is for regular user, always only single local and single remote
        self.local_site, self.remote_site = \
            self.sync_server.get_sites_for_project(self._project)

        self.projection = self.get_default_projection()

        self.sort = self.DEFAULT_SORT

        self.query = self.get_default_query()
        self.default_query = list(self.get_default_query())
        log.debug("!!! init query: {}".format(json.dumps(self.query,
                                                         indent=4)))
        representations = self.dbcon.aggregate(self.query)
        self.refresh(representations)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(self.REFRESH_SEC)

    @property
    def dbcon(self):
        return self.sync_server.connection.database[self._project]

    def data(self, index, role):
        item = self._data[index.row()]

        if role == Qt.DisplayRole:
            return attr.asdict(item)[self._header[index.column()]]
        if role == Qt.UserRole:
            return item._id

    def rowCount(self, index):
        return len(self._data)

    def columnCount(self, index):
        return len(self._header)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return str(self._header[section])

    def tick(self):
        self.refresh(representations=None, load_records=self._rec_loaded)
        self.timer.start(self.REFRESH_SEC)

    def get_header_index(self, value):
        """
            Returns index of 'value' in headers

            Args:
                value (str): header name value
            Returns:
                (int)
        """
        return self._header.index(value)

    def refresh(self, representations=None, load_records=0):
        self.beginResetModel()
        self._data = []
        self._rec_loaded = 0

        if not representations:
            self.query = self.get_default_query(load_records)
            representations = self.dbcon.aggregate(self.query)

        self._add_page_records(self.local_site, self.remote_site,
                               representations)
        self.endResetModel()

    def _add_page_records(self, local_site, remote_site, representations):
        for repre in representations:
            context = repre.get("context").pop()
            files = repre.get("files", [])
            if isinstance(files, dict):  # aggregate returns dictionary
                files = [files]

            # representation without files doesnt concern us
            if not files:
                continue

            local_updated = remote_updated = None
            if repre.get('updated_dt_local'):
                local_updated = \
                    repre.get('updated_dt_local').strftime("%Y%m%dT%H%M%SZ")

            if repre.get('updated_dt_remote'):
                remote_updated = \
                    repre.get('updated_dt_remote').strftime("%Y%m%dT%H%M%SZ")

            avg_progress_remote = repre.get('avg_progress_remote', '')
            avg_progress_local = repre.get('avg_progress_local', '')

            item = self.SyncRepresentation(
                repre.get("_id"),
                context.get("asset"),
                context.get("subset"),
                "v{:0>3d}".format(context.get("version", 1)),
                context.get("representation"),
                local_updated,
                remote_updated,
                '{} {}'.format(local_site, avg_progress_local),
                '{} {}'.format(remote_site, avg_progress_remote),
                repre.get("files_count", 1),
                repre.get("files_size", 0),
                1,
                STATUS[repre.get("status", -1)]
            )

            self._data.append(item)
            self._rec_loaded += 1

    def canFetchMore(self, index):
        """
            Check if there are more records than currently loaded
        """
        # 'skip' might be suboptimal when representation hits 500k+
        self._buffer = list(self.dbcon.aggregate(self.query))
        # log.info("!!! canFetchMore _rec_loaded::{} - {}".format(
        #     self._rec_loaded, len(self._buffer)))
        return len(self._buffer) > self._rec_loaded

    def fetchMore(self, index):
        """
            Add more record to model.

            Called when 'canFetchMore' returns true, which means there are
            more records in DB than loaded.
            'self._buffer' is used to stash cursor to limit requery
        """
        log.debug("fetchMore")
        # cursor.count() returns always total number, not only skipped + limit
        remainder = len(self._buffer) - self._rec_loaded
        items_to_fetch = min(self.PAGE_SIZE, remainder)
        self.beginInsertRows(index,
                             self._rec_loaded,
                             self._rec_loaded + items_to_fetch - 1)

        self._add_page_records(self.local_site, self.remote_site, self._buffer)

        self.endInsertRows()

        self.numberPopulated.emit(items_to_fetch)  # ??

    def sort(self, index, order):
        """
            Summary sort per representation.

            Sort is happening on a DB side, model is reset, db queried
            again.

            Args:
                index (int): column index
                order (int): 0|
        """
        # limit unwanted first re-sorting by view
        if index < 0:
            return

        self._rec_loaded = 0
        if order == 0:
            order = 1
        else:
            order = -1

        self.sort = {self.SORT_BY_COLUMN[index]: order, '_id': 1}
        self.query = self.get_default_query()

        representations = self.dbcon.aggregate(self.query)
        self.refresh(representations)

    def set_filter(self, filter):
        """
            Adds text value filtering

            Args:
                filter (str): string inputted by user
        """
        self.filter = filter
        self.refresh()

    def set_project(self, project):
        """
            Changes project, called after project selection is changed

            Args:
                project (str): name of project
        """
        self._project = project
        self.refresh()

    def get_index(self, id):
        """
            Get index of 'id' value.

            Used for keeping selection after refresh.

            Args:
                id (str): MongoDB _id
            Returns:
                (QModelIndex)
        """
        index = None
        for i in range(self.rowCount(None)):
            index = self.index(i, 0)
            value = self.data(index, Qt.UserRole)
            if value == id:
                return index
        return index

    def get_default_query(self, limit=0):
        """
            Returns basic aggregate query for main table.

            Main table provides summary information about representation,
            which could have multiple files. Details are accessible after
            double click on representation row.
            Columns:
                'created_dt' - max of created or updated (when failed) per repr
                'sync_dt' - same for remote side
                'local_site' - progress of repr on local side, 1 = finished
                'remote_site' - progress on remote side, calculates from files
                'state' -
                    0 - queued
                    1 - failed
                    2 - paused (not implemented yet)
                    3 - in progress
                    4 - finished on both sides

                are calculated and must be calculated in DB because of
                pagination

            Args:
                limit (int): how many records should be returned, by default
                    it 'PAGE_SIZE' for performance.
                    Should be overridden by value of loaded records for refresh
                    functionality (got more records by scrolling, refresh
                    shouldn't reset that)
        """
        if limit == 0:
            limit = SyncRepresentationModel.PAGE_SIZE

        return [
            {"$match": self._get_match_part()},
            {'$unwind': '$files'},
            # merge potentially unwinded records back to single per repre
            {'$addFields': {
                'order_remote': {
                    '$filter': {'input': '$files.sites', 'as': 'p',
                                'cond': {'$eq': ['$$p.name', self.remote_site]}
                                }}
                , 'order_local': {
                    '$filter': {'input': '$files.sites', 'as': 'p',
                                'cond': {'$eq': ['$$p.name', self.local_site]}
                                }}
            }},
            {'$addFields': {
                # prepare progress per file, presence of 'created_dt' denotes
                # successfully finished load/download
                'progress_remote': {'$first': {
                    '$cond': [{'$size': "$order_remote.progress"},
                              "$order_remote.progress", {'$cond': [
                                {'$size': "$order_remote.created_dt"}, [1],
                                [0]]}]}}
                , 'progress_local': {'$first': {
                    '$cond': [{'$size': "$order_local.progress"},
                              "$order_local.progress", {'$cond': [
                                {'$size': "$order_local.created_dt"}, [1],
                                [0]]}]}}
                # file might be successfully created or failed, not both
                , 'updated_dt_remote': {'$first': {
                    '$cond': [{'$size': "$order_remote.created_dt"},
                              "$order_remote.created_dt",
                              {'$cond': [
                                {'$size': "$order_remote.last_failed_dt"},
                                "$order_remote.last_failed_dt",
                                []]
                               }]}}
                , 'updated_dt_local': {'$first': {
                    '$cond': [{'$size': "$order_local.created_dt"},
                              "$order_local.created_dt",
                              {'$cond': [
                                {'$size': "$order_local.last_failed_dt"},
                                "$order_local.last_failed_dt",
                                []]
                               }]}}
                , 'files_size': {'$ifNull': ["$files.size", 0]}
                , 'failed_remote': {
                    '$cond': [{'$size': "$order_remote.last_failed_dt"}, 1, 0]}
                , 'failed_local': {
                    '$cond': [{'$size': "$order_local.last_failed_dt"}, 1, 0]}
            }},
            {'$group': {
                '_id': '$_id'
                # pass through context - same for representation
                , 'context': {'$addToSet': '$context'}
                # pass through files as a list
                , 'files': {'$addToSet': '$files'}
                # count how many files
                , 'files_count': {'$sum': 1}
                , 'files_size': {'$sum': '$files_size'}
                # sum avg progress, finished = 1
                , 'avg_progress_remote': {'$avg': "$progress_remote"}
                , 'avg_progress_local': {'$avg': "$progress_local"}
                # select last touch of file
                , 'updated_dt_remote': {'$max': "$updated_dt_remote"}
                , 'failed_remote': {'$sum': '$failed_remote'}
                , 'failed_local': {'$sum': '$failed_local'}
                , 'updated_dt_local': {'$max': "$updated_dt_local"}
            }},
            {"$sort": self.sort},
            {"$limit": limit},
            {"$skip": self._rec_loaded},
            {"$project": self.projection}
        ]

    def _get_match_part(self):
        """
            Extend match part with filter if present.

            Filter is set by user input. Each model has different fields to be
            checked.
            If performance issues are found, '$text' and text indexes should
            be investigated.
        """
        if not self.filter:
            return {
                "type": "representation",
                'files.sites': {
                    '$elemMatch': {
                        '$or': [
                            {'name': self.local_site},
                            {'name': self.remote_site}
                        ]
                    }
                }
            }
        else:
            regex_str = '.*{}.*'.format(self.filter)
            return {
                "type": "representation",
                '$or': [{'context.subset':  {'$regex': regex_str,
                                             '$options': 'i'}},
                        {'context.asset': {'$regex': regex_str,
                                           '$options': 'i'}},
                        {'context.representation': {'$regex': regex_str,
                                                    '$options': 'i'}}],
                'files.sites': {
                    '$elemMatch': {
                        '$or': [
                            {'name': self.local_site},
                            {'name': self.remote_site}
                        ]
                    }
                }
            }

    def get_default_projection(self):
        """
            Projection part for aggregate query.

            All fields with '1' will be returned, no others.

            Returns:
                (dict)
        """
        return {
            "context.subset": 1,
            "context.asset": 1,
            "context.version": 1,
            "context.representation": 1,
            "files": 1,
            'files_count': 1,
            "files_size": 1,
            'avg_progress_remote': 1,
            'avg_progress_local': 1,
            'updated_dt_remote': 1,
            'updated_dt_local': 1,
            'status': {
                '$switch': {
                    'branches': [
                        {
                            'case': {
                                '$or': [{'$eq': ['$avg_progress_remote', 0]},
                                        {'$eq': ['$avg_progress_local', 0]}]},
                            'then': 0
                        },
                        {
                            'case': {
                                '$or': ['$failed_remote', '$failed_local']},
                            'then': 1
                        },
                        {
                            'case': {'$or': [{'$and': [
                                    {'$gt': ['$avg_progress_remote', 0]},
                                    {'$lt': ['$avg_progress_remote', 1]}
                                ]},
                                {'$and': [
                                    {'$gt': ['$avg_progress_local', 0]},
                                    {'$lt': ['$avg_progress_local', 1]}
                                ]}
                            ]},
                            'then': 2
                        },
                        {
                            'case': {'$eq': ['dummy_placeholder', 'paused']},
                            'then': 3
                        },
                        {
                            'case': {'$and': [
                                {'$eq': ['$avg_progress_remote', 1]},
                                {'$eq': ['$avg_progress_local', 1]}
                            ]},
                            'then': 4
                        },
                    ],
                    'default': -1
                }
            }
        }


class SyncServerDetailWindow(QtWidgets.QDialog):
    def __init__(self, sync_server, _id, project,  parent=None):
        log.debug(
            "!!! SyncServerDetailWindow _id:: {}".format(_id))
        super(SyncServerDetailWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        self.setStyleSheet(style.load_stylesheet())
        self.setWindowIcon(QtGui.QIcon(style.app_icon_path()))
        self.resize(1000, 400)

        body = QtWidgets.QWidget()
        footer = QtWidgets.QWidget()
        footer.setFixedHeight(20)

        container = SyncRepresentationDetailWidget(sync_server, _id, project,
                                                   parent=self)
        body_layout = QtWidgets.QHBoxLayout(body)
        body_layout.addWidget(container)
        body_layout.setContentsMargins(0, 0, 0, 0)

        message = QtWidgets.QLabel()
        message.hide()

        footer_layout = QtWidgets.QVBoxLayout(footer)
        footer_layout.addWidget(message)
        footer_layout.setContentsMargins(0, 0, 0, 0)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(body)
        layout.addWidget(footer)

        self.setLayout(body_layout)
        self.setWindowTitle("Sync Representation Detail")


class SyncRepresentationDetailWidget(QtWidgets.QWidget):
    """
        Widget to display list of synchronizable files for single repre.

        Args:
            _id (str): representation _id
            project (str): name of project with repre
            parent (QDialog): SyncServerDetailWindow
    """
    active_changed = QtCore.Signal()    # active index changed

    default_widths = (
        ("file", 290),
        ("created_dt", 120),
        ("sync_dt", 120),
        ("local_site", 60),
        ("remote_site", 60),
        ("size", 60),
        ("priority", 20),
        ("state", 90)
    )

    def __init__(self, sync_server, _id=None, project=None, parent=None):
        super(SyncRepresentationDetailWidget, self).__init__(parent)

        self.representation_id = _id
        self.item = None  # set to item that mouse was clicked over

        self.sync_server = sync_server

        self._selected_id = None

        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("Filter representation..")

        top_bar_layout = QtWidgets.QHBoxLayout()
        top_bar_layout.addWidget(self.filter)

        self.table_view = QtWidgets.QTableView()
        headers = [item[0] for item in self.default_widths]

        model = SyncRepresentationDetailModel(sync_server, headers, _id,
                                              project)
        self.table_view.setModel(model)
        self.table_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table_view.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self.table_view.setSelectionBehavior(
            QtWidgets.QTableView.SelectRows)
        self.table_view.horizontalHeader().setSortIndicator(-1,
                                                            Qt.AscendingOrder)
        self.table_view.setSortingEnabled(True)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().hide()

        time_delegate = PrettyTimeDelegate(self)
        column = self.table_view.model().get_header_index("created_dt")
        self.table_view.setItemDelegateForColumn(column, time_delegate)
        column = self.table_view.model().get_header_index("sync_dt")
        self.table_view.setItemDelegateForColumn(column, time_delegate)

        column = self.table_view.model().get_header_index("local_site")
        delegate = ImageDelegate(self)
        self.table_view.setItemDelegateForColumn(column, delegate)

        column = self.table_view.model().get_header_index("remote_site")
        delegate = ImageDelegate(self)
        self.table_view.setItemDelegateForColumn(column, delegate)

        column = self.table_view.model().get_header_index("size")
        delegate = SizeDelegate(self)
        self.table_view.setItemDelegateForColumn(column, delegate)

        for column_name, width in self.default_widths:
            idx = model.get_header_index(column_name)
            self.table_view.setColumnWidth(idx, width)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top_bar_layout)
        layout.addWidget(self.table_view)

        self.filter.textChanged.connect(lambda: model.set_filter(
            self.filter.text()))
        self.table_view.customContextMenuRequested.connect(
            self._on_context_menu)

        self.table_view.model().modelReset.connect(self._set_selection)

        self.selection_model = self.table_view.selectionModel()
        self.selection_model.selectionChanged.connect(self._selection_changed)

    def _selection_changed(self):
        index = self.selection_model.currentIndex()
        self._selected_id = self.table_view.model().data(index, Qt.UserRole)

    def _set_selection(self):
        """
            Sets selection to 'self._selected_id' if exists.

            Keep selection during model refresh.
        """
        if self._selected_id:
            index = self.table_view.model().get_index(self._selected_id)
            if index.isValid():
                mode = QtCore.QItemSelectionModel.Select | \
                       QtCore.QItemSelectionModel.Rows
                self.selection_model.setCurrentIndex(index, mode)
            else:
                self._selected_id = None

    def _show_detail(self):
        """
            Shows windows with error message for failed sync of a file.
        """
        dt = max(self.item.created_dt, self.item.sync_dt)
        detail_window = SyncRepresentationErrorWindow(self.item._id,
                                                      self.project,
                                                      dt,
                                                      self.item.tries,
                                                      self.item.error)
        detail_window.exec()

    def _on_context_menu(self, point):
        """
            Shows menu with loader actions on Right-click.
        """
        point_index = self.table_view.indexAt(point)
        if not point_index.isValid():
            return

        self.item = self.table_view.model()._data[point_index.row()]

        menu = QtWidgets.QMenu()
        actions_mapping = {}

        if self.item.state == STATUS[1]:
            action = QtWidgets.QAction("Open error detail")
            actions_mapping[action] = self._show_detail
            menu.addAction(action)

        remote_site, remote_progress = self.item.remote_site.split()
        if remote_progress == '1':
            action = QtWidgets.QAction("Reset local site")
            actions_mapping[action] = self._reset_local_site
            menu.addAction(action)

        local_site, local_progress = self.item.local_site.split()
        if local_progress == '1':
            action = QtWidgets.QAction("Reset remote site")
            actions_mapping[action] = self._reset_remote_site
            menu.addAction(action)

        if not actions_mapping:
            action = QtWidgets.QAction("< No action >")
            actions_mapping[action] = None
            menu.addAction(action)

        result = menu.exec_(QtGui.QCursor.pos())
        if result:
            to_run = actions_mapping[result]
            if to_run:
                to_run()

    def _reset_local_site(self):
        """
            Removes errors or success metadata for particular file >> forces
            redo of upload/download
        """
        self.sync_server.reset_provider_for_file(
            self.table_view.model()._project,
            self.representation_id,
            self.item._id,
            'local')

    def _reset_remote_site(self):
        """
            Removes errors or success metadata for particular file >> forces
            redo of upload/download
        """
        self.sync_server.reset_provider_for_file(
            self.table_view.model()._project,
            self.representation_id,
            self.item._id,
            'remote')


class SyncRepresentationDetailModel(QtCore.QAbstractTableModel):
    """
        List of all syncronizable files per single representation.
    """
    PAGE_SIZE = 30
    # TODO add filter filename
    DEFAULT_SORT = {
        "files.path": 1
    }
    SORT_BY_COLUMN = [
        "files.path",
        "updated_dt_local",     # local created_dt
        "updated_dt_remote",    # remote created_dt
        "progress_local",       # local progress
        "progress_remote",      # remote progress
        "size",                 # remote progress
        "context.asset",        # priority TODO
        "status"                # state
    ]

    @attr.s
    class SyncRepresentationDetail:
        """
            Auxiliary object for easier handling.

            Fields must contain all header values (+ any arbitrary values).
        """
        _id = attr.ib()
        file = attr.ib()
        created_dt = attr.ib(default=None)
        sync_dt = attr.ib(default=None)
        local_site = attr.ib(default=None)
        remote_site = attr.ib(default=None)
        size = attr.ib(default=None)
        priority = attr.ib(default=None)
        state = attr.ib(default=None)
        tries = attr.ib(default=None)
        error = attr.ib(default=None)

    def __init__(self, sync_server, header, _id, project=None):
        super(SyncRepresentationDetailModel, self).__init__()
        self._header = header
        self._data = []
        self._project = project
        self._rec_loaded = 0
        self.filter = None
        self._buffer = []  # stash one page worth of records (actually cursor)
        self._id = _id
        self._initialized = False

        self.sync_server = sync_server
        # TODO think about admin mode
        # this is for regular user, always only single local and single remote
        self.local_site, self.remote_site = \
            self.sync_server.get_sites_for_project(self._project)

        self.sort = self.DEFAULT_SORT

        # in case we would like to hide/show some columns
        self.projection = self.get_default_projection()

        self.query = self.get_default_query()
        import bson.json_util
        # log.debug("detail init query:: {}".format(
        #     bson.json_util.dumps(self.query, indent=4)))
        representations = self.dbcon.aggregate(self.query)
        self.refresh(representations)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(SyncRepresentationModel.REFRESH_SEC)

    @property
    def dbcon(self):
        return self.sync_server.connection.database[self._project]

    def tick(self):
        self.refresh(representations=None, load_records=self._rec_loaded)
        self.timer.start(SyncRepresentationModel.REFRESH_SEC)

    def get_header_index(self, value):
        """
            Returns index of 'value' in headers

            Args:
                value (str): header name value
            Returns:
                (int)
        """
        return self._header.index(value)

    def data(self, index, role):
        item = self._data[index.row()]
        if role == Qt.DisplayRole:
            return attr.asdict(item)[self._header[index.column()]]
        if role == Qt.UserRole:
            return item._id

    def rowCount(self, index):
        return len(self._data)

    def columnCount(self, index):
        return len(self._header)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return str(self._header[section])

    def refresh(self, representations=None, load_records=0):
        self.beginResetModel()
        self._data = []
        self._rec_loaded = 0

        if not representations:
            self.query = self.get_default_query(load_records)
            representations = self.dbcon.aggregate(self.query)

        self._add_page_records(self.local_site, self.remote_site,
                               representations)
        self.endResetModel()

    def _add_page_records(self, local_site, remote_site, representations):
        """
            Process all records from 'representation' and add them to storage.

            Args:
                local_site (str): name of local site (mine)
                remote_site (str): name of cloud provider (theirs)
                representations (Mongo Cursor)
        """
        for repre in representations:
            # log.info("!!! repre:: {}".format(repre))
            files = repre.get("files", [])
            if isinstance(files, dict):  # aggregate returns dictionary
                files = [files]

            for file in files:
                local_updated = remote_updated = None
                if repre.get('updated_dt_local'):
                    local_updated = \
                        repre.get('updated_dt_local').strftime(
                            "%Y%m%dT%H%M%SZ")

                if repre.get('updated_dt_remote'):
                    remote_updated = \
                        repre.get('updated_dt_remote').strftime(
                            "%Y%m%dT%H%M%SZ")

                progress_remote = repre.get('progress_remote', '')
                progress_local = repre.get('progress_local', '')

                errors = []
                if repre.get('failed_remote_error'):
                    errors.append(repre.get('failed_remote_error'))
                if repre.get('failed_local_error'):
                    errors.append(repre.get('failed_local_error'))

                item = self.SyncRepresentationDetail(
                    file.get("_id"),
                    os.path.basename(file["path"]),
                    local_updated,
                    remote_updated,
                    '{} {}'.format(local_site, progress_local),
                    '{} {}'.format(remote_site, progress_remote),
                    file.get('size', 0),
                    1,
                    STATUS[repre.get("status", -1)],
                    repre.get("tries"),
                    '\n'.join(errors)
                )
                self._data.append(item)
                self._rec_loaded += 1

    def canFetchMore(self, index):
        """
            Check if there are more records than currently loaded
        """
        # 'skip' might be suboptimal when representation hits 500k+
        self._buffer = list(self.dbcon.aggregate(self.query))
        return len(self._buffer) > self._rec_loaded

    def fetchMore(self, index):
        """
            Add more record to model.

            Called when 'canFetchMore' returns true, which means there are
            more records in DB than loaded.
            'self._buffer' is used to stash cursor to limit requery
        """
        log.debug("fetchMore")
        # cursor.count() returns always total number, not only skipped + limit
        remainder = len(self._buffer) - self._rec_loaded
        items_to_fetch = min(self.PAGE_SIZE, remainder)

        self.beginInsertRows(index,
                             self._rec_loaded,
                             self._rec_loaded + items_to_fetch - 1)
        self._add_page_records(self.local_site, self.remote_site, self._buffer)

        self.endInsertRows()

    def sort(self, index, order):
        # limit unwanted first re-sorting by view
        if index < 0:
            return

        self._rec_loaded = 0  # change sort - reset from start

        if order == 0:
            order = 1
        else:
            order = -1

        self.sort = {self.SORT_BY_COLUMN[index]: order}
        self.query = self.get_default_query()

        representations = self.dbcon.aggregate(self.query)
        self.refresh(representations)

    def set_filter(self, filter):
        self.filter = filter
        self.refresh()

    def get_index(self, id):
        """
            Get index of 'id' value.

            Used for keeping selection after refresh.

            Args:
                id (str): MongoDB _id
            Returns:
                (QModelIndex)
        """
        index = None
        for i in range(self.rowCount(None)):
            index = self.index(i, 0)
            value = self.data(index, Qt.UserRole)
            if value == id:
                return index
        return index

    def get_default_query(self, limit=0):
        """
            Gets query that gets used when no extra sorting, filtering or
            projecting is needed.

            Called for basic table view.

            Returns:
                [(dict)] - list with single dict - appropriate for aggregate
                    function for MongoDB
        """
        if limit == 0:
            limit = SyncRepresentationModel.PAGE_SIZE

        return [
            {"$match": self._get_match_part()},
            {"$unwind": "$files"},
            {'$addFields': {
                'order_remote': {
                    '$filter': {'input': '$files.sites', 'as': 'p',
                                'cond': {'$eq': ['$$p.name', self.remote_site]}
                                }}
                , 'order_local': {
                    '$filter': {'input': '$files.sites', 'as': 'p',
                                'cond': {'$eq': ['$$p.name', self.local_site]}
                                }}
            }},
            {'$addFields': {
                # prepare progress per file, presence of 'created_dt' denotes
                # successfully finished load/download
                'progress_remote': {'$first': {
                    '$cond': [{'$size': "$order_remote.progress"},
                              "$order_remote.progress", {'$cond': [
                                {'$size': "$order_remote.created_dt"},
                                [1],
                                [0]]}]}}
                , 'progress_local': {'$first': {
                    '$cond': [{'$size': "$order_local.progress"},
                              "$order_local.progress", {'$cond': [
                                {'$size': "$order_local.created_dt"},
                                [1],
                                [0]]}]}}
                # file might be successfully created or failed, not both
                , 'updated_dt_remote': {'$first': {
                    '$cond': [{'$size': "$order_remote.created_dt"},
                              "$order_remote.created_dt",
                              {'$cond': [
                                  {'$size': "$order_remote.last_failed_dt"},
                                  "$order_remote.last_failed_dt",
                                  []]
                              }
                             ]}}
                , 'updated_dt_local': {'$first': {
                    '$cond': [{'$size': "$order_local.created_dt"},
                              "$order_local.created_dt",
                              {'$cond': [
                                  {'$size': "$order_local.last_failed_dt"},
                                  "$order_local.last_failed_dt",
                                  []]
                              }
                             ]}}
                , 'failed_remote': {
                    '$cond': [{'$size': "$order_remote.last_failed_dt"}, 1, 0]}
                , 'failed_local': {
                    '$cond': [{'$size': "$order_local.last_failed_dt"}, 1, 0]}
                , 'failed_remote_error': {'$first': {
                    '$cond': [{'$size': "$order_remote.error"},
                              "$order_remote.error", [""]]}}
                , 'failed_local_error': {'$first': {
                    '$cond': [{'$size': "$order_local.error"},
                              "$order_local.error", [""]]}}
                , 'tries': {'$first': {
                    '$cond': [{'$size': "$order_local.tries"},
                              "$order_local.tries",
                              {'$cond': [
                                  {'$size': "$order_remote.tries"},
                                  "$order_remote.tries",
                                  []]
                              }]}}
            }},
            {"$sort": self.sort},
            {"$limit": limit},
            {"$skip": self._rec_loaded},
            {"$project": self.projection}
        ]

    def _get_match_part(self):
        """
            Returns different content for 'match' portion if filtering by
            name is present

            Returns:
                (dict)
        """
        if not self.filter:
            return {
                "type": "representation",
                "_id": self._id
            }
        else:
            regex_str = '.*{}.*'.format(self.filter)
            return {
                "type": "representation",
                "_id": self._id,
                '$or': [{'files.path': {'$regex': regex_str,
                                        '$options': 'i'}}]
            }

    def get_default_projection(self):
        """
            Projection part for aggregate query.

            All fields with '1' will be returned, no others.

            Returns:
                (dict)
        """
        return {
            "files": 1,
            'progress_remote': 1,
            'progress_local': 1,
            'updated_dt_remote': 1,
            'updated_dt_local': 1,
            'failed_remote_error': 1,
            'failed_local_error': 1,
            'tries': 1,
            'status': {
                '$switch': {
                    'branches': [
                        {
                            'case': {
                                '$or': [{'$eq': ['$progress_remote', 0]},
                                        {'$eq': ['$progress_local', 0]}]},
                            'then': 0
                        },
                        {
                            'case': {
                                '$or': ['$failed_remote', '$failed_local']},
                            'then': 1
                        },
                        {
                            'case': {'$or': [{'$and': [
                                {'$gt': ['$progress_remote', 0]},
                                {'$lt': ['$progress_remote', 1]}
                            ]},
                                {'$and': [
                                    {'$gt': ['$progress_local', 0]},
                                    {'$lt': ['$progress_local', 1]}
                                ]}
                            ]},
                            'then': 2
                        },
                        {
                            'case': {'$eq': ['dummy_placeholder', 'paused']},
                            'then': 3
                        },
                        {
                            'case': {'$and': [
                                {'$eq': ['$progress_remote', 1]},
                                {'$eq': ['$progress_local', 1]}
                            ]},
                            'then': 4
                        },
                    ],
                    'default': -1
                }
            }
        }


class ImageDelegate(QtWidgets.QStyledItemDelegate):
    """
        Prints icon of site and progress of synchronization
    """
    def __init__(self, parent=None):
        super(ImageDelegate, self).__init__(parent)
        self.icons = {}

    def paint(self, painter, option, index):
        option = QtWidgets.QStyleOptionViewItem(option)
        option.showDecorationSelected = True

        if (option.showDecorationSelected and
                (option.state & QtWidgets.QStyle.State_Selected)):
            painter.setOpacity(0.20)  # highlight color is a bit off
            painter.fillRect(option.rect,
                             option.palette.highlight())
            painter.setOpacity(1)

        d = index.data(QtCore.Qt.DisplayRole)
        if d:
            provider, value = d.split()
        else:
            return

        if not self.icons.get(provider):
            resource_path = os.path.dirname(__file__)
            resource_path = os.path.join(resource_path, "..",
                                         "providers", "resources")
            pix_url = "{}/{}.png".format(resource_path, provider)
            pixmap = QtGui.QPixmap(pix_url)
            self.icons[provider] = pixmap
        else:
            pixmap = self.icons[provider]

        point = QtCore.QPoint(option.rect.x() +
                              (option.rect.width() - pixmap.width()) / 2,
                              option.rect.y() +
                              (option.rect.height() - pixmap.height()) / 2)
        painter.drawPixmap(point, pixmap)

        painter.setOpacity(0.5)
        overlay_rect = option.rect
        overlay_rect.setHeight(overlay_rect.height() * (1.0 - float(value)))
        painter.fillRect(overlay_rect,
                         QtGui.QBrush(QtGui.QColor(0, 0, 0, 200)))
        painter.setOpacity(1)

class SyncRepresentationErrorWindow(QtWidgets.QDialog):
    def __init__(self, _id, project, dt, tries, msg, parent=None):
        super(SyncRepresentationErrorWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        self.setStyleSheet(style.load_stylesheet())
        self.setWindowIcon(QtGui.QIcon(style.app_icon_path()))
        self.resize(250, 200)

        body = QtWidgets.QWidget()
        footer = QtWidgets.QWidget()
        footer.setFixedHeight(20)

        container = SyncRepresentationErrorWidget(_id, project, dt, tries, msg,
                                                  parent=self)
        body_layout = QtWidgets.QHBoxLayout(body)
        body_layout.addWidget(container)
        body_layout.setContentsMargins(0, 0, 0, 0)

        message = QtWidgets.QLabel()
        message.hide()

        footer_layout = QtWidgets.QVBoxLayout(footer)
        footer_layout.addWidget(message)
        footer_layout.setContentsMargins(0, 0, 0, 0)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(body)
        layout.addWidget(footer)

        self.setLayout(body_layout)
        self.setWindowTitle("Sync Representation Error Detail")


class SyncRepresentationErrorWidget(QtWidgets.QWidget):
    """
        Dialog to show when sync error happened, prints error message
    """
    def __init__(self, _id, project, dt, tries, msg, parent=None):
        super(SyncRepresentationErrorWidget, self).__init__(parent)

        layout = QtWidgets.QFormLayout(self)
        layout.addRow(QtWidgets.QLabel("Last update date"),
                      QtWidgets.QLabel(pretty_timestamp(dt)))
        layout.addRow(QtWidgets.QLabel("Retries"),
                      QtWidgets.QLabel(str(tries)))
        layout.addRow(QtWidgets.QLabel("Error message"),
                      QtWidgets.QLabel(msg))


class SizeDelegate(QtWidgets.QStyledItemDelegate):
    """
        Pretty print for file size
    """
    def __init__(self, parent=None):
        super(SizeDelegate, self).__init__(parent)

    def displayText(self, value, locale):
        if value is None:
            # Ignore None value
            return

        return self._pretty_size(value)

    def _pretty_size(self, value, suffix='B'):
        for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
            if abs(value) < 1024.0:
                return "%3.1f%s%s" % (value, unit, suffix)
            value /= 1024.0
        return "%.1f%s%s" % (value, 'Yi', suffix)

