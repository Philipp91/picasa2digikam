"""Migrates metadata of photos from .picasa.ini files to a digiKam SQLite database."""

import configparser
import logging
import os
import traceback
import xml.etree.ElementTree as ET

from pathlib import Path
from typing import Dict, List, Optional, Set

from picasa2digikam.digikam_db import DigikamDb
import picasa2digikam.rect64 as rect64

_PICASA_INI_FILE = '.picasa.ini'
_OLD_PICASA_INI_FILE = 'Picasa.ini' # found this in folders from 2002!
_PICASA_TAG_NAME = 'Picasa'
_UNKNOWN_FACE_ID = 'ffffffffffffffff'
_FACE_TAG_REGION_PROPERTY = 'tagRegion'

ContactTags = Dict[str, Optional[int]]
GlobalNames = Dict[str, str] # maps contact_id to name globally (but may be overridden per directory)
ContactID2NamesSet = Dict[str, Set[str]]

_PHOTO_AND_VIDEO_EXTENSIONS = {
    # Photo:
    '.jpg',
    '.jpeg',
    '.raw',
    '.psd',
    '.webp',
    # Video:
    '.mkv',  # Matroska
    '.mp4',  # MPEG-4
    '.mov',  # QuickTime
    '.avi',  # Audio Video Interleave
    '.wmv',  # Windows Media Video
    '.flv',  # Flash Video
    '.webm', # Web Media
    '.mpeg', # MPEG-1 or MPEG-2
    '.mpg',  # MPEG (alternate extension)
    '.m4v',  # MPEG-4 Apple variant
    '.3gp',  # 3GPP
    '.3g2',  # 3GPP2
    '.ogv',  # Ogg Video
}

def _is_photo_or_video_file(file: str) -> bool:
    return Path(file).suffix.lower() in _PHOTO_AND_VIDEO_EXTENSIONS

def learn_contact_ids(input_dir: Path, ini_file_name: str, contact_id_2_nameset: ContactID2NamesSet):
    """Learn contact_id to name mapping from [Contacts2] sections of .ini file"""
    # Read ini file.
    ini = configparser.ConfigParser(strict=False)
    ini_file = Path(input_dir) / ini_file_name
    ini.read(ini_file, encoding='utf8')
    if 'Contacts2' in ini:
        for contact_id, value in ini['Contacts2'].items():
            person_name = value.split(';')[0]
            if contact_id not in contact_id_2_nameset:
                logging.info(f'Learned name for {contact_id}=\'{person_name}\' from {ini_file}')
                contact_id_2_nameset[contact_id] = {person_name}
            else:
                if person_name not in contact_id_2_nameset[contact_id]:
                    logging.warning(f"Learned additional name for {contact_id}='{person_name}' from {ini_file}")
                contact_id_2_nameset[contact_id].add(person_name)

    # Note: the difference between 'Contacts2'_and 'Contacts' is we don't add extra names to the set
    #       when read from 'Contacts' since the name is just a hash
    if 'Contacts' in ini:
        for contact_id, value in ini['Contacts'].items():
            picasa_name_hash = value.split(',')[1]
            person_name = f'.NoName-{picasa_name_hash}'
            if contact_id not in contact_id_2_nameset:
                logging.info(f'Learned old picasa name hash for {contact_id}=\'{person_name}\' from {ini_file}')
                contact_id_2_nameset[contact_id] = {person_name}

def migrate_directories_under(input_root_dir: Path, 
                              db: DigikamDb, 
                              dry_run: bool,
                              contacts_file: Optional[Path],
                              skip_same_rect: Optional[bool]):
    """Traverses directory tree to find directories to migrate."""

    # Build a contact_id to name(s) dictionary
    global_names: GlobalNames = {}
    prioritize_global_names = False
    
    if contacts_file is not None:
        # contacts.xml seems more authoritative than *.ini files
        # Use this whenever possible.
        prioritize_global_names = True
        logging.debug(f'Reading contacts from {contacts_file}')
        tree = ET.parse(contacts_file)
        for contact in tree.getroot():
            logging.debug(f'{contact.attrib}')
            global_names[contact.attrib['id']] = contact.attrib['name']

    else:
        # Alternate way using *.ini files
        # Sometimes names will be missing or conflicting if found 
        # different in multiple directories.  Conflicting names
        # will be merged by this script by concatenating them with " | " 
        # separators in sorted order.  
        contact_id_2_nameset: ContactID2NamesSet = {}
        for input_dir, subdirs, files in os.walk(input_root_dir):
            for ini_file in ( _PICASA_INI_FILE , _OLD_PICASA_INI_FILE):
                learn_contact_ids(input_dir,ini_file,contact_id_2_nameset)

        global_names = {k: '|'.join(sorted(v)) for k, v in contact_id_2_nameset.items()}

        logging.debug(f'global_names={global_names}')

    contact_tags_per_dir: Dict[Path, ContactTags] = {}

    for input_dir, subdirs, files in os.walk(input_root_dir):
        dir = Path(input_dir)
        if _PICASA_INI_FILE in files:
            ini_file = _PICASA_INI_FILE
        elif _OLD_PICASA_INI_FILE in files:
            ini_file = _OLD_PICASA_INI_FILE
        else:
            if any(_is_photo_or_video_file(file) for file in files):
                logging.warning(f'Found photos but no .ini in {dir}')
            else:
                logging.warning(f'No photos and no .ini file in {dir}')
            continue
        logging.debug(f'Processing {Path(dir / ini_file)}')
        contact_tags_per_dir[dir] = migrate_directory(dir, files, db,
            	contact_tags_per_dir, global_names,
            	dry_run=dry_run, ini_file_name=ini_file,
            	prioritize_global_names=prioritize_global_names,
            	skip_same_rect=skip_same_rect)

def migrate_directory(input_dir: Path, files: List[str], db: DigikamDb,
                      contact_tags_per_dir: Dict[Path, ContactTags],
                      global_names: GlobalNames,
                      dry_run: bool,
                      ini_file_name: str,
                      prioritize_global_names: bool,
                      skip_same_rect: Optional[bool]) -> ContactTags:
    """Migrates metadata of all photo files in the given directory."""
    logging.info('===========================================================================================')
    if input_dir.name == '.picasaoriginals':
        logging.info(f'Skipping {input_dir}')
        return {}
    logging.info(f'Now migrating {input_dir}')

    # Find digiKam album.
    album_id = db.find_album_by_dir(input_dir)
    if album_id is None:
        return {} 
        
    album_images = db.get_album_images(album_id)

    # Read ini file.
    ini = configparser.ConfigParser(strict=False)
    ini_file = input_dir / ini_file_name
    try:
        ini.read(ini_file, encoding='utf8')
    except Exception as err:
        raise RuntimeError(f'Failed to read ini file "{ini_file}".') from err
    used_ini_sections = {'Picasa', 'Contacts', 'Contacts2'}

    # Create or look up digiKam tags for each Picasa album and contact/person.
    album_to_tag = _map_albums_to_tags(ini, db, used_ini_sections, dry_run=dry_run)

    self_contact_to_tag = _map_contacts_to_tags(ini['Contacts2'], db, dry_run=dry_run) if 'Contacts2' in ini else {}
    logging.debug(f'self_contact_to_tag={self_contact_to_tag}')
    
    # Merge contacts declared in parent ini files.
    contact_to_tag = self_contact_to_tag.copy()
    for parent_dir in input_dir.parents:
        for contact_id, tag_id in contact_tags_per_dir.get(parent_dir, {}).items():
            if contact_id in contact_to_tag:
                # The tag_id is a bijective mapping of the contact name.
                # This check detects situations where the same Picasa contact ID
                # maps to different person names (and thus different tag_ids) at
                # different levels of the picasa.ini hierarchy. This can happen
                # when the user renamed the person in Picasa before writing to one
                # and after writing to the other directory.
                if contact_to_tag[contact_id] != tag_id:
                    error_msg = (
                        f'In the {_PICASA_INI_FILE} files in {input_dir} and {parent_dir}, ' +
                        f'the contact with ID {contact_id} has different names. Please open ' +
                        f'up those files and adjust the names to be the same everywhere.'
                    )
                    logging.error(error_msg)
                    if not dry_run:
                        raise ValueError(error_msg)
            else:
                contact_to_tag[contact_id] = tag_id

    # Migrate file by file.
    for filename in filter(_is_photo_or_video_file, files):
        if filename not in album_images:
            raise ValueError(f'digiKam does not know {(input_dir / filename)}')
        image_id = album_images[filename]
        if ini.has_section(filename):
            used_ini_sections.add(filename)
            ini_section = ini[filename]
            try:
                migrate_file(filename, image_id, ini_section, db, album_to_tag, contact_to_tag, global_names, 
                             skip_same_rect=skip_same_rect, prioritize_global_names=prioritize_global_names, 
                             dry_run=dry_run)
            except Exception as e:
                logging.error(f'Exception: {e}')
                logging.error(traceback.format_exc())
                raise RuntimeError(f'Error when processing {input_dir / filename}') from e

    # Make sure we actually read all the data from the ini file.
    unused_ini_sections = set(ini.sections()) - used_ini_sections
    unused_photo_sections = {section for section in unused_ini_sections if _is_photo_or_video_file(section)}
    if unused_photo_sections:
        logging.warning(
            f'Some files have metadata in {ini_file} but are gone (probably fine, they might have been ' +
            f'deleted or moved elsewhere on purpose): {unused_photo_sections}')
    unused_ini_sections -= unused_photo_sections
    if unused_ini_sections:
        logging.warning(f'Unused INI sections in {ini_file}: {unused_ini_sections}')

    return self_contact_to_tag  # For use in subdirectories

def migrate_file(filename: str, image_id: int, ini_section: configparser.SectionProxy, db: DigikamDb,
                 album_to_tag: Dict[str, int],     # Picasa ID -> digiKam Tag ID
                 contact_to_tag: ContactTags,      # Picasa contact ID -> digiKam Tag ID (local to this directory branch -- use this if possible, but might not be complete)
                 global_names: GlobalNames,        # Picasa contact ID -> name (global to whole picasa source tree -- might be ambiguous)
                 dry_run: bool,
                 prioritize_global_names: bool,
                 skip_same_rect: Optional[bool]):
    # Note: Picasa's rotate=rotate(N) means 0=normal, 1=90º, 2=180º, 3=270º clock-wise. This does *not* influence the
    # face coordinates, which are wrt. the image file stored on disk.
    used_ini_keys = {'backuphash', 'rotate'}
    if ini_section.getboolean('star'):
        used_ini_keys.add('star')
        if db.image_has_pick_tag(image_id):
            logging.warning(
                f'Not applying star label to {image_id} ({filename}) because it already has a Pick label')
        else:
            logging.debug(f'Applying star label to {image_id} ({filename})')
            if not dry_run:
                db.star_image(image_id)

    albums = ini_section.get('albums')
    if albums:
        used_ini_keys.add('albums')
        for album_id in albums.split(','):
            logging.debug(f'Adding album {album_id} to image {image_id} ({filename})')
            if not dry_run:
                db.add_image_tag(image_id, album_to_tag[album_id])

    faces = ini_section.get('faces')
    if faces:
        used_ini_keys.add('faces')
        if filename.lower().endswith('.psd'):
            # Note: digiKam doesn't seem to know the size of PSD files and thus also
            # can't place face tags on them.
            logging.warning(f'Skipping faces on {filename} because of PSD format')
        else:
            for face_data in faces.split(';'):
                migrate_face(image_id, filename, face_data, db, contact_to_tag, global_names, 
                             prioritize_global_names=prioritize_global_names, 
                             skip_same_rect=skip_same_rect, 
                             dry_run=dry_run)

    unused_ini_keys = set(ini_section.keys()) - used_ini_keys
    if unused_ini_keys:
        logging.warning(f'Unused INI keys for {filename}: {unused_ini_keys}')


def migrate_face(image_id: int, 
                 filename: str, 
                 face_data: str, 
                 db: DigikamDb, 
                 contact_to_tag: ContactTags, 
                 global_names: GlobalNames,
                 dry_run: bool,
                 prioritize_global_names: bool,
                 skip_same_rect: Optional[bool]):
    face_data = face_data.split(',')
    assert len(face_data) == 2
    if face_data[1] == _UNKNOWN_FACE_ID:
        return
    contact_id = face_data[1]

    tag_id = None

    if not prioritize_global_names:
        # Names from local directory's .ini files have higher priority
        if contact_id in contact_to_tag:
            tag_id = contact_to_tag[contact_id]
        else:
            if contact_id not in global_names:
                # This can happen often if not using contacts.xml
                # Add to global
                person_name = f'.NoName-{contact_id}-from-rect64'
                logging.info(f'Learned {person_name} from a rect64 tag belonging to {filename}')
                global_names[contact_id] = person_name
            tag_id = db.find_or_create_person_tag(global_names[contact_id], dry_run=dry_run)
            contact_to_tag[contact_id] = tag_id
    else:
        # global_names (learned from contacts.xml) has higher priority
        if contact_id in global_names:
            tag_id = db.find_or_create_person_tag(global_names[contact_id], dry_run=dry_run)
            contact_to_tag[contact_id] = tag_id
        elif contact_id in contact_to_tag:
            tag_id = contact_to_tag[contact_id]
        else:
            person_name = f'.NoName-{contact_id}-from-rect64'
            logging.info(f'Learned {person_name} from a rect64 tag belonging to {filename}')
            global_names[contact_id] = person_name
            tag_id = db.find_or_create_person_tag(person_name, dry_run=dry_run)
            contact_to_tag[contact_id] = tag_id

    if db.image_has_tag(image_id, tag_id):
        logging.warning(
            f'Not applying face {tag_id} ({contact_id}) to {image_id} ({filename}) because it already has that face tag')
        return

    # Convert the rectangle.
    image_size = db.get_image_size(image_id)
    picasa_rect = rect64.parse_rect64(face_data[0])
    digikam_rect = rect64.to_digikam_rect(image_size, picasa_rect)

    # Not sure if skipping an existing rect is an improvement or not... probably not since DigiKam creates rects at scan time
    # and if the same rect is found in Picasa, it won't migrate.
    # Should NOT skip if it is the first attempt at migration. however if you don't skip and identify the rect as someone else
    # and then run this script again, you end up with another rect mapped to Picasa's name -- it's a conundrum..
    if db.image_has_property(image_id, _FACE_TAG_REGION_PROPERTY, digikam_rect):
        if skip_same_rect is None:
            raise RuntimeError(
                f'digiKam already has face rectangle {digikam_rect} defined. ' +
                'Please specify what to do by running with argument --skip_same_rect or --no-skip_same_rect')
        elif skip_same_rect:
            logging.warning(
                f'Not applying face {tag_id} ({contact_id}) to {image_id} ({filename}) because it already has that face rectangle')
            return

    logging.debug(f'Adding face {tag_id} ({contact_id}) at {digikam_rect} to {image_id} ({filename})')
    if dry_run:
        return

    # Insert the tag into the digiKam database.
    # Skip if the person is already tagged anywhere on that photo in the digiKam database.
    if db.add_image_tag(image_id, tag_id):
        # A new tag was added, so we need to provide the coordinates.
        db.set_image_tag_property(image_id, tag_id, _FACE_TAG_REGION_PROPERTY, digikam_rect)


def _map_albums_to_tags(
        ini: configparser.ConfigParser, db: DigikamDb, used_ini_sections: Set[str], dry_run: bool
) -> Dict[str, int]:  # Picasa ID -> digiKam Tag ID
    picasa_tag = db.find_or_create_tag(parent_tag=0, name=_PICASA_TAG_NAME, dry_run=dry_run)
    result = {}
    for section_name in ini.sections():
        if section_name.startswith('.album:'):
            album_id = section_name[7:]
            section = ini[section_name]
            if not 'name' in section:
                logging.debug(f'Skipping unnamed album {album_id}')
                continue
            assert section['name']
            used_ini_sections.add(section_name)
            assert album_id == section['token']
            tag_id = db.find_or_create_tag(parent_tag=picasa_tag, name=section['name'], dry_run=dry_run)
            result[album_id] = tag_id
    return result


def _map_contacts_to_tags(
        contacts_section: configparser.SectionProxy, db: DigikamDb, dry_run: bool
) -> ContactTags:  # Picasa ID -> digiKam Tag ID
    # works for "[Contacts2]" section_name
    result = {}
    for contact_id, value in contacts_section.items():
        person_name = value.split(';')[0]
        result[contact_id] = db.find_or_create_person_tag(person_name, dry_run=dry_run)
        logging.debug(f'person_name={person_name} contact_id={contact_id} tag={result[contact_id]}')
    return result
