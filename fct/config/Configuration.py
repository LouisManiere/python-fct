
"""
Configuration Classes
"""

import os
from pathlib import Path
import glob
from collections import namedtuple
from configparser import ConfigParser
from base64 import urlsafe_b64encode
import yaml
import click

from shapely.geometry import shape
import fiona

Tile = namedtuple('Tile', ('gid', 'row', 'col', 'x0', 'y0', 'bounds', 'tileset'))
DataSource = namedtuple('DataSource', ('name', 'filename', 'resolution'))

def strip(s):
    # return re.sub(' {2,}', ' ', s.strip())
    return s.rstrip()

def from_srs(srs):
    """
    Return SRID from EPSG Identifier
    """

    if srs.startswith('EPSG:'):
        return int(srs[5:])

    return 0

class Workspace:
    """
    Shared parameters and output dataset definitions
    """

    # def __init__(self, workspace, datasets):
    def __init__(self):

        self._workdir = ''
        self._outputdir = ''
        self._tileset = 'default'
        # self._datasets = datasets
        self._srs = ''
        self._srid = 0

    #     if 'workdir' in workspace:
    #         self._workdir = workspace['workdir']

    #     if 'srs' in workspace:
    #         self._srs = workspace['srs']
    #         self._srid = from_srs(self._srs)

    # def dataset(self, name):
    #     """
    #     Return named Dataset
    #     """

    #     # if not name in self._datasets:
    #     #     self._datasets[name] = Dataset(name)

    #     return self._datasets[name]

    def copy(self):
        """
        Returns a deep copy of this object
        """

        # pylint: disable=protected-access

        other = Workspace()
        other._workdir = self._workdir
        other._outputdir = self._outputdir
        other._tileset = self._tileset
        other._srs = self._srs
        other._srid = self._srid

        return other

    @property
    def workdir(self):
        """
        Return working directory
        """
        return self._workdir

    @property
    def outputdir(self):
        return self._outputdir

    def set_outputdir(self, outputdir):
        self._outputdir = outputdir

    @property
    def tileset(self):
        return self._tileset

    @property
    def srid(self):
        """
        Return SRID
        """
        return self._srid

    @property
    def srs(self):
        """
        Return SRS Identifier
        """
        return self._srs

    def set_srs(self, srs):
        """
        Set SRS
        """

        self._srs = srs
        self._srid = from_srs(srs)

class Configuration():
    """
    Configuration singleton,
    which can be read from a .ini file.

    Configuration defines:

    - datasources
    - tilesets
    - datasets
    - shared parameters: workdir, srid
    """

    def __init__(self):

        self._tilesets = dict()
        self._datasources = dict()
        self._datasets = dict()
        self._touched = set()
        self._workspace = Workspace()

    def auto(self):
        """
        Populate configuration from `config.ini`
        defined in `FCT_CONFIG` environment variable.
        Use .env if exists.
        """

        # pylint: disable=import-outside-toplevel

        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))

        if 'FCT_CONFIG' in os.environ:

            filename = os.environ['FCT_CONFIG']
            click.secho('FCT_CONFIG=%s' % filename, fg='yellow')
            self.from_file(filename)

    def default(self):
        """
        Populate configuration from default `config.ini`
        """

        filename = os.path.join(os.path.dirname(__file__), 'config.ini')
        self.configure(*FileParser.parse(filename))

    def from_file(self, filename):
        """
        Populate configuration from .ini file
        """
        self.configure(*FileParser.parse(filename))

    @property
    def workspace(self):
        return self._workspace
    
    def set_workspace(self, workspace):
        self._workspace = workspace

    # def dataset(self, name):
    #     """
    #     Return Dataset definition
    #     """
    #     return self._workspace.dataset(name)

    def dataset(self, name):
        """
        Return Dataset by name/key
        """

        # if not name in self._datasets:
        #     self._datasets[name] = Dataset(name)

        self._touched.add(name)
        return self._datasets[name]

    @property
    def touched(self):
        """
        Return list of datasets which have been accessed or created
        during processing session
        """
        return list(self._touched)

    def temporary_dataset(self, name):

        template = self.dataset(name)

        while True:

            temp = template.mktemp()

            if temp.name not in self._datasets:

                self._datasets[temp.name] = temp
                return temp

    # def fileset(self, names, **kwargs):
    #     """
    #     Return list of Dataset filename instances
    #     """
    #     return [
    #         self.filename(name, **kwargs)
    #         for name in names
    #     ]

    def tileset(self, name='default'):
        """
        Return Tileset definition
        """

        if name == 'default':
            if 'FCT_TILESET' in os.environ:
                if os.environ['FCT_TILESET'] in self._tilesets:
                    name = os.environ['FCT_TILESET']

        return self._tilesets[name]

    def datasource(self, name):
        """
        Return DataSource definition
        """
        return self._datasources[name]

    def filename(self, name, **kwargs):
        """
        Return Dataset filename instance
        """

        dst = self.dataset(name)

        outputdir = kwargs.get('outputdir', self.workspace.outputdir)

        if outputdir:

            path1 = (
                Path(self.workdir) /
                outputdir /
                dst.subdir(**kwargs) /
                dst.filename(**kwargs)
            )

        else:

            path1 = (
                Path(self.workdir) /
                dst.subdir(**kwargs) /
                dst.filename(**kwargs)
            )

        if path1.exists():
            return path1

        # TODO check if we should create resource or not

        path2 = (
            Path(self.workdir) /
            dst.subdir(**kwargs) /
            dst.filename(**kwargs)
        )

        if path2.exists():
            return path2

        if not path1.parent.exists():
            try:
                path1.parent.mkdir(parents=True)
            except FileExistsError:
                pass

        return path1

    # def mod(self, name, **kwargs):
    #     """
    #     Check if there exists a modified version of dataset `name`
    #     """

    #     warn = False

    #     if 'FCT_MOD' in os.environ:

    #         if os.environ['FCT_MOD'] == 'disable':
    #             return None

    #         if os.environ['FCT_MOD'] == 'warn':
    #             warn = True

    #     dst = self.dataset(name)

    #     folder = os.path.join(
    #         self.workdir,
    #         dst.subdir(**kwargs))

    #     if not os.path.exists(folder):
    #         os.makedirs(folder)

    #     mod_filename = os.path.join(
    #         folder,
    #         'MOD',
    #         dst.filename(**kwargs))

    #     if not os.path.exists(mod_filename):
    #         return None

    #     if warn:

    #         dst = self.dataset(name)
    #         basename = os.path.join(
    #             dst.subdir(**kwargs),
    #             'MOD',
    #             dst.filename(**kwargs)
    #         )

    #         click.secho(
    #             'WARN (mod) %s => %s' % (name, basename),
    #             fg='yellow')

    #     return mod_filename

    def basename(self, name, **kwargs):
        """
        Return Dataset filename relative to workdir
        """

        dst = self.dataset(name)

        return os.path.join(
            dst.subdir(**kwargs),
            dst.filename(**kwargs))

    @property
    def workdir(self):
        """
        Return working directory
        """
        return self._workspace.workdir

    @property
    def srid(self):
        """
        Return SRID
        """
        return self._workspace.srid

    @property
    def vertical_ref(self):
        """
        Vertical reference system for elevations
        """

        return strip("""
            VERT_CS["NGF-IGN69 height",
                VERT_DATUM["Nivellement General de la France - IGN69",2005,
                    AUTHORITY["EPSG","5119"]],
                UNIT["metre",1,
                    AUTHORITY["EPSG","9001"]],
                AXIS["Up",UP],
                AUTHORITY["EPSG","5720"]]
        """)

    def axes(self, name):
        """
        Returns all axes defined in named dataset
        """

        axis_shapefile = self.filename(name)

        with fiona.open(axis_shapefile) as fs:
            for feature in fs:

                axis = feature['properties']['AXIS']
                yield axis

    def configure(self, workspace, datasources, datasets, tilesets):
        """
        Populate configuration
        """

        for tileset in tilesets.values():
            tileset.parent = self

        self._workspace = workspace
        self._datasources = datasources
        self._datasets = datasets
        self._tilesets = tilesets

class Dataset():
    """
    Describes an output dataset
    """

    def __init__(self, name, properties, filename='', tilename='', subdir='', ext='.tif'):

        self._name = name
        self._properties = properties
        self._filename = filename
        self._tilename = tilename
        self._subdir = subdir
        self._ext = ext

        if filename == '':
            self._filename = name.upper() + ext

        if tilename == '':
            self._tilename = name.upper() + '_%(row)02d_%(col)02d'

    def mktemp(self):

        suffix = urlsafe_b64encode(os.urandom(6)).decode('ascii')
        temp_name = '_'.join([self._name, suffix])
        basename, extension = os.path.splitext(self._filename)
        temp_filename = '_'.join([basename, suffix]) + extension
        temp_tilename = ''

        return Dataset(
            temp_name,
            self._properties.copy(),
            temp_filename,
            temp_tilename,
            os.path.join(self._subdir, 'TEMP'),
            self._ext)

    @property
    def name(self):
        """
        Return dataset's name
        """
        return self._name

    @property
    def properties(self):
        return self._properties

    def subdir(self, **kwargs):
        """
        Return storage subdirectory
        """

        if 'subdir' in kwargs:
            return kwargs['subdir']

        return self._subdir % kwargs

    @property
    def ext(self):
        """
        Return file extension
        """
        return self._ext

    @property
    def basename(self):

        if self._tilename is None:
            raise ValueError('Dataset %s does not have tiles' % self.name)

        if '_%' in self._tilename:
            parts = self._tilename.split('_%')
            return parts[0]

        if '%' in self._tilename:
            parts = self._tilename.split('%')
            return parts[0]

        return self._tilename

    def filename(self, **kwargs):
        """
        Return filename instance
        """

        if self._filename is None:
            raise ValueError('Dataset %s has only tiles' % self.name)

        if kwargs:
            return self._filename % kwargs

        return self._filename

    def tilename(self, **kwargs):
        """
        Return tilename instance
        """

        if self._tilename is None:
            raise ValueError('Dataset %s does not have tiles' % self.name)

        if kwargs:
            return (self._tilename + self.ext) % kwargs

        return self._tilename

class Tileset():
    """
    Describes a tileset from a shapefile index
    """

    def __init__(self, name, index, height, width, tiledir, resolution):

        self._name = name
        self._index = index
        self._height = height
        self._width = width
        self._bounds = None
        self._length = 0
        self._tileindex = None
        self._tiledir = tiledir
        self._resolution = resolution
        self._is_configured = False
        self.parent = None

    def configure(self):

        if self._is_configured:
            return

        with fiona.open(self._index) as fs:
            self._bounds = fs.bounds
            self._length = len(fs)
            self._row_min = min(f['properties']['ROW'] for f in fs)
            self._col_min = min(f['properties']['COL'] for f in fs)

        self._is_configured = True

    @property
    def name(self):
        """
        Name of this tileset
        """
        return self._name

    @property
    def height(self):
        """
        Height in pixels of one tile
        """
        return self._height

    @property
    def width(self):
        """
        Width in pixels of one tile
        """
        return self._width

    @property
    def resolution(self):
        return self._resolution

    @property
    def bounds(self):
        """
        (minx, miny, maxx, maxy) bounds of this tileset
        """
        self.configure()
        return self._bounds

    @property
    def tiledir(self):
        """
        Tile storage relative to dataset path
        """
        return self._tiledir

    @property
    def tileindex(self):
        """
        Index of tiles belonging to this tileset
        """

        if self._tileindex is None:

            index = dict()

            with fiona.open(self._index) as fs:

                for feature in fs:
                    props = feature['properties']
                    values = [props[k] for k in ('GID', 'ROW', 'COL', 'X0', 'Y0')]
                    values.append(shape(feature['geometry']).bounds)
                    values.append(self.name)
                    tile = Tile(*values)
                    index[(tile.row, tile.col)] = tile

            self._tileindex = index

        return self._tileindex

    def __len__(self):
        """
        Return number of tiles in tileindex
        """

        self.configure()
        return self._length

    def tiles(self):
        """
        Generator of tiles
        """

        with fiona.open(self._index) as fs:
            for feature in fs:

                props = feature['properties']
                values = [props[k] for k in ('GID', 'ROW', 'COL', 'X0', 'Y0')]
                values.append(shape(feature['geometry']).bounds)
                values.append(self.name)
                yield Tile(*values)

    def index(self, x, y):
        """
        Return tile coordinates of real world point (x, y)
        """

        self.configure()
        minx, _, _, maxy = self._bounds
        row = int((maxy - y) // self._resolution) + self._row_min
        col = int((x - minx) // self._resolution) + self._col_min
        return row, col

    def filename(self, dataset, **kwargs):
        """
        Return dataset main file with tileset qualifier
        """

        dst = self.parent.dataset(dataset)
        basename, extension = os.path.splitext(dst.filename(**kwargs))
        name = ''.join([basename, '_', self.tiledir, extension])

        outputdir = kwargs.get('outputdir', self.parent.workspace.outputdir)

        if outputdir:

            path1 = (
                Path(self.parent.workspace.workdir) /
                outputdir /
                dst.subdir(**kwargs) /
                name
            )

        else:

            path1 = (
                Path(self.parent.workspace.workdir) /
                dst.subdir(**kwargs) /
                name
            )

        if path1.exists():
            return path1

        # TODO check if we should create resource or not

        path2 = (
            Path(self.parent.workspace.workdir) /
            dst.subdir(**kwargs) /
            name
        )

        if path2.exists():
            return path2

        if not path1.parent.exists():
            try:
                path1.parent.mkdir(parents=True)
            except FileExistsError:
                pass

        return path1

    def tilename(self, dataset, row, col, **kwargs):
        """
        Return full-path filename instance for specific tile
        """

        dst = self.parent.dataset(dataset)
        filename = dst.tilename(row=row, col=col, **kwargs)

        outputdir = kwargs.get('outputdir', self.parent.workspace.outputdir)

        if outputdir:

            path1 = (
                Path(self.parent.workspace.workdir) /
                outputdir /
                dst.subdir(**kwargs) /
                self.tiledir /
                dst.basename /
                filename
            )

        else:

            path1 = (
                Path(self.parent.workspace.workdir) /
                dst.subdir(**kwargs) /
                self.tiledir /
                dst.basename /
                filename
            )

        if path1.exists():
            return path1

        # TODO check if we should create resource or not

        path2 = (
            Path(self.parent.workspace.workdir) /
            dst.subdir(**kwargs) /
            self.tiledir /
            dst.basename /
            filename
        )

        if path2.exists():
            return path2

        if not path1.parent.exists():
            try:
                path1.parent.mkdir(parents=True)
            except FileExistsError:
                pass

        return path1

class FileParser():
    """
    Read configuration components form a .ini file
    """

    @staticmethod
    def parse(configfile):
        """
        Main parsing method
        """

        parser = ConfigParser()
        parser.read(configfile)

        sections = list()
        datasources = dict()
        tilesets = dict()
        workspace = Workspace()

        for section in parser.sections():

            if section in ('Workspace', 'DataSources', 'Tilesets'):
                sections.append(section)
                continue

            items = dict(parser.items(section))

            if 'type' in items:
                item_type = items['type']
                if item_type == 'datasource':
                    datasources[section] = FileParser.datasource(section, items)
                elif item_type == 'tileset':
                    tilesets[section] = FileParser.tileset(section, items)

        while sections:

            section = sections.pop()

            if section == 'Workspace':
                for key, value in parser.items(section):
                    setattr(workspace, '_' + key, value)
                    
                    if key=='srs':
                        workspace.set_srs(value)
                        
            elif section == 'DataSources':
                for key, value in parser.items(section):
                    if value in datasources:
                        datasources[key] = datasources[value]
                    else:
                        raise KeyError(value)
            elif section == 'Tilesets':
                for key, value in parser.items(section):
                    if value in tilesets:

                        tilesets[key] = tilesets[value]

                        if 'FCT_TILEDIR' in os.environ:
                            if 'FCT_TILESET' in os.environ and os.environ['FCT_TILESET'] == key:
                                tiledir = os.environ['FCT_TILEDIR']
                                tilesets[key]._tiledir = tiledir
                                click.secho('Override %s\'s tile directory to %s' % (key, tiledir), fg='cyan')

                    else:
                        raise KeyError(value)

        datasets = FileParser.datasets(
            FileParser.load_dataset_yaml(configfile))

        return workspace, datasources, datasets, tilesets

    @staticmethod
    def datasource(name, items):
        """
        Populate a DataSource object
        """

        filename = items.get('filename', None)
        resolution = float(items.get('resolution', 0.0))
        return DataSource(name, filename, resolution)

    @staticmethod
    def tileset(name, items):
        """
        Populate a Tileset object
        """

        index = items['index']
        tiledir = items['tiledir']
        height = int(items['height'])
        width = int(items['width'])
        resolution = float(items['resolution'])

        return Tileset(name, index, height, width, tiledir, resolution)

    @staticmethod
    def load_dataset_yaml_file(filename):

        # click.echo('Loading dataset definitions from %s' % filename)

        with open(filename) as fp:
            return yaml.safe_load(fp)

    @staticmethod
    def load_dataset_yaml_dir(dirname):

        # click.echo('Loading dataset definitions from %s' % dirname)

        data = dict()

        for name in glob.glob(os.path.join(dirname, '*.yml')):
            with open(name) as fp:
                data.update(yaml.safe_load(fp))

        return data

    @staticmethod
    def load_dataset_yaml(configfile):
        """
        Read dataset definitions from `datasets` directory
        or from ``datasets.yml`
        """

        dstdir = os.path.join(
            os.path.dirname(configfile),
            'datasets')

        if os.path.isdir(dstdir):

            return FileParser.load_dataset_yaml_dir(dstdir)

        dstfile = os.path.join(
            os.path.dirname(configfile),
            'datasets.yml')

        if os.path.exists(dstfile):

            return FileParser.load_dataset_yaml_file(dstfile)

        dstdir = os.path.join(
            os.path.dirname(__file__),
            'datasets')

        if os.path.isdir(dstdir):

            return FileParser.load_dataset_yaml_dir(dstdir)

        dstfile = os.path.join(
            os.path.dirname(__file__),
            'datasets.yml')

        if os.path.exists(dstfile):

            return FileParser.load_dataset_yaml_file(dstfile)

        raise ValueError('Cannot find dataset definition files')

    @staticmethod
    def datasets(data):
        """
        Read YAML dataset definitions
        and return a dict of datasets
        """

        datasets = dict()

        for name in data:

            filename = data[name].get('filename', None)
            subdir = data[name]['subdir']

            if 'tiles' in data[name]:

                tilename = data[name]['tiles']['template']
                ext = data[name]['tiles']['extension']

            else:

                tilename = None
                ext = None

            dst = Dataset(name, data[name], filename, tilename, subdir, ext)
            datasets[name] = dst

        return datasets
