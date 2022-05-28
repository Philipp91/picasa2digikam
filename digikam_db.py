import logging
import os
import psutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path, WindowsPath
from typing import Any, Dict, List, Optional, Set, Tuple

_INTERNAL_ROOT_TAG_NAME = '_Digikam_Internal_Tags_'
_TAG_PROPERTY_PERSON = 'person'
_TAG_PROPERTY_FACE_ENGINE = 'faceEngineId'


@dataclass
class DigikamDb(object):
    file: Path
    conn: sqlite3.Connection
    album_roots: Dict[Path, int]  # path => ID
    person_root_tag: int  # Tag ID of the "Persons" tag.
    internal_tags_id: int  # Tag ID of the "_Digikam_Internal_Tags_" tag.
    pick_tags: List[int]  # IDs of the "Pick" labels
    star_tag: int  # Tag ID assigned to starred photos, usually it's the "Pick" label "Accepted" (green flag icon).

    def __init__(self, file: Path):
        self.file = file
        logging.info("file=%s" % file)
        self.conn = sqlite3.connect(file)
        if os.name == 'nt':  # Windows
            import win32api  # From the pywin32 PIP package.
            serial_to_mountpoints: Dict[int, Set[str]] = {}
            for sdiskpart in psutil.disk_partitions():
                _, serial, _, _, _ = win32api.GetVolumeInformation(sdiskpart.mountpoint)
                if serial < 0:
                    serial = serial + (1 << 32)  # Convert int32 to uint32
                serial_to_mountpoints.setdefault(serial, set()).add(sdiskpart.mountpoint)
            logging.info('serial_to_mountpoints=%s' % serial_to_mountpoints)
            def volume_uuid_to_mountpoints(uuid: str) -> Set[str]:
                # On Windows, digiKam uses the serial number in hex format as the UUID:
                # https://invent.kde.org/frameworks/solid/-/blob/006e013d18c20cf2c98cf1776d768476978a1a63/src/solid/devices/backends/win/winstoragevolume.cpp#L57
                return serial_to_mountpoints[int(uuid, 16)]
        else:  # Tested on Linux
            dev_to_mountpoints: Dict[str, Set[str]] = {}
            for sdiskpart in psutil.disk_partitions():
                dev_to_mountpoints.setdefault(sdiskpart.device, set()).add(sdiskpart.mountpoint)
            logging.info('dev_to_mountpoints=%s' % dev_to_mountpoints)
            def volume_uuid_to_mountpoints(uuid: str) -> Set[str]:
                # On Unix, we use a trick with realpath and /dev/disk/by-uuid' to find the main mount point.
                return dev_to_mountpoints[os.path.realpath(Path('/dev/disk/by-uuid') / uuid.upper())]

        self.album_roots = {}
        for row in self.conn.cursor().execute('SELECT id, type, identifier, specificPath FROM AlbumRoots WHERE status = 0'):
            id, type, identifier, specific_path = row
            if type != 1 and type != 2 and type != 3:  # 0=Undefined, 1=VolumeHardWired, 2=VolumeRemovable, 3=Network
                logging.info('Skipping album %s at %s on %s because it is not a local disk' % (id, specific_path, identifier))
                continue
            logging.info('id=%s specific_path=%s identifier=%s' % (id, specific_path, identifier))
            if identifier.startswith('volumeid:?uuid='):
                if specific_path.startswith('/'):
                    specific_path = specific_path[1:]
                for mountpoint in volume_uuid_to_mountpoints(identifier[15:]):
                    self.album_roots[Path(mountpoint) / specific_path] = id
            elif identifier.startswith('volumeid:?path='):
                self.album_roots[identifier[15:]] = id
            elif identifier.startswith('networkshareid:?mountpath='):
                self.album_roots[identifier[26:]] = id
            else:
                raise ValueError('Unsupported volume type %s' % identifier)
                
        logging.info('album_roots=%s' % self.album_roots)

        self.person_root_tag = self._detect_person_root_tag()
        self.internal_tags_id = self.find_tag(0, _INTERNAL_ROOT_TAG_NAME)
        self.star_tag = self.find_tag(self.internal_tags_id, 'Pick Label Accepted')
        self.pick_tags = [
            self.star_tag,
            self.find_tag(self.internal_tags_id, 'Pick Label Pending'),
            self.find_tag(self.internal_tags_id, 'Pick Label Rejected'),
            self.find_tag(self.internal_tags_id, 'Pick Label None'),
        ]
        assert self.star_tag

    def close(self):
        self.conn.close()

    def find_album_by_dir(self, path: Path) -> int:
        """Returns ID of the Album that contains the given path."""
        for root_path, root_id in self.album_roots.items():
            try:
                relative_path = path.relative_to(root_path).as_posix()
                if relative_path == '.':
                    relative_path = '/'  # Different ways of expressing the root.
                else:
                    relative_path = '/' + relative_path  # digiKam stores them with a leading slash, weirdly.
            except ValueError:
                continue
            album_id = self._fetchcell('SELECT id FROM Albums WHERE albumRoot = ? AND relativePath = ?',
                                       (root_id, relative_path))
            if album_id is None:
                raise ValueError('No digiKam Album found for %s (relative path %s) under root %s' % (path, relative_path, root_id))
            return album_id
        raise ValueError('No digiKam AlbumRoot found for %s, only have %s' % (path, self.album_roots))

    def get_album_images(self, album_id: int) -> Dict[str, id]:
        """Returns a dict from filename to id in Images."""
        return self._fetchdict('SELECT name, id FROM Images WHERE album = ? and status = 1', (album_id,))

    def get_image_size(self, image_id: int) -> Tuple[int, int, int]:
        """Returns the width and height in pixels, plus the orientation code."""
        cur = self.conn.cursor()
        cur.execute('SELECT width, height, orientation FROM ImageInformation WHERE imageid = ?', (image_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError('Image with ID %s not found' % image_id)
        if not row[0] or not row[1]:
            raise ValueError('Size of image with ID %s is not in the database' % image_id)
        return row[0], row[1], row[2]

    def find_tag(self, parent_tag: int, name: str) -> Optional[int]:
        """Returns the ID of the tag with the given name under the given parent tag, or None if it does not exist."""
        return self._fetchcell('SELECT id FROM Tags WHERE pid = ? AND name = ?', (parent_tag, name))

    def find_or_create_tag(self, parent_tag: int, name: str, dry_run: bool) -> int:
        """Returns the ID of a possibly newly created tag with the given name under the given parent tag."""
        tag_id = self.find_tag(parent_tag, name)
        if tag_id:
            return tag_id
        logging.info('Creating digiKam tag %s' % name)
        if dry_run:
            return -1  # Pretend we created it
        self.conn.execute('INSERT INTO Tags (pid, name) VALUES (?, ?)', (parent_tag, name))
        tag_id = self.find_tag(parent_tag, name)
        assert tag_id
        return tag_id

    def get_parent_tag(self, tag: int) -> int:
        parent_tag = self._fetchcell('SELECT pid FROM Tags WHERE id = ?', (tag,))
        assert parent_tag is not None
        return parent_tag

    def _detect_person_root_tag(self) -> int:
        result = self.find_tag(parent_tag=0, name='Persons') or self.find_tag(parent_tag=0, name='Personen')
        if result:
            return result
        # This is a little fallback hack: We just look which tags contain person annotations, and then walk up.
        some_person_tag = self._fetchcell('SELECT tagid FROM TagProperties WHERE property = "person"')
        if not some_person_tag:
            raise RuntimeError('Looks like the digiKam database does not contain a "Persons" tag')
        person_root_tag = self.get_parent_tag(some_person_tag)
        assert self.get_parent_tag(person_root_tag) == 0  # Ensure we're actually at the root of the tag hierarchy.
        return person_root_tag

    def find_person_tag(self, person_name: str) -> Optional[int]:
        """Returns the ID of the person tag, or None if it does not exist."""
        return self._fetchcell('SELECT id FROM Tags WHERE pid = ? AND name = ?', (self.person_root_tag, person_name))

    def find_or_create_person_tag(self, person_name: str, dry_run: bool) -> int:
        """Returns the ID of a possibly newly created person tag with the given name."""
        tag_id = self.find_person_tag(person_name)
        if tag_id:
            return tag_id
        logging.info('Creating digiKam person tag %s' % person_name)
        if dry_run:
            return -1  # Pretend we created it
        self.conn.execute('INSERT INTO Tags (pid, name) VALUES (?, ?)', (self.person_root_tag, person_name))
        tag_id = self.find_person_tag(person_name)
        assert tag_id
        self.conn.executemany('INSERT INTO TagProperties (tagid, property, value) VALUES (?, ?, ?)',
                              [(tag_id, _TAG_PROPERTY_PERSON, person_name),
                               (tag_id, _TAG_PROPERTY_FACE_ENGINE, person_name)])
        return tag_id

    def image_has_tag(self, image_id: int, tag_id: int) -> bool:
        """Returns true if the given image already has the given tag."""
        return self._fetchcell(
            'SELECT tagid FROM ImageTags WHERE imageid = ? AND tagid = ?',
            (image_id, tag_id)) is not None

    def image_has_pick_tag(self, image_id: int) -> bool:
        """Returns true if the given image has any of the (four) "Pick" tags."""
        return self._fetchcell(
            'SELECT tagid FROM ImageTags WHERE imageid = ? AND tagid IN (%s)' % ','.join('?' * len(self.pick_tags)),
            (image_id,) + tuple(self.pick_tags)) is not None

    def add_image_tag(self, image_id: int, tag_id: int) -> bool:
        """Adds a tag to an image and returns True. Ignores and returns False if it already exists."""
        return self.conn.execute(
            'INSERT INTO ImageTags (imageid, tagid) VALUES (?, ?) ON CONFLICT(imageid, tagid) DO NOTHING',
            (image_id, tag_id)).rowcount > 0

    def set_image_tag_property(self, image_id: int, tag_id: int, propname: str, value: str):
        """Sets an image tag property, or fails if it already exists."""
        self.conn.execute('INSERT INTO ImageTagProperties (imageid, tagid, property, value) VALUES (?, ?, ?, ?)',
                          (image_id, tag_id, propname, value))

    def star_image(self, image_id: int):
        """Adds the equivalent of a Picasa star to the given image."""
        self.add_image_tag(image_id, self.star_tag)

    def _fetchcell(self, query: str, *args) -> Any:
        cur = self.conn.cursor()
        cur.execute(query, *args)
        row = cur.fetchone()
        return None if row is None else row[0]

    def _fetchdict(self, query: str, *args) -> Dict[Any, Any]:
        result = {}
        for row in self.conn.cursor().execute(query, *args):
            result[row[0]] = row[1]
        return result
