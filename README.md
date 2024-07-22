# picasa2digikam

A script to migrate Picasa metadata from its `.picasa.ini` files and/or `contacts.xml` file to the 
[digiKam](https://www.digikam.org/) database.

It does not require Picasa to be installed and therefore does not require Windows. 

It does not write into the original Picasa file system, so the original files should remain untouched.  


## Supported metadata

* Picasa stars => Set "Pick" tag to "Accepted" in digiKam
* Picasa albums => digiKam tags
    - Note that Picasa's "tags" (with the yellow tag icon) are stored inside the image files themselves (metadata), and
      digiKam imports them automatically, so this script does not touch them. If you have a Picasa album and a Picasa
      tag of the same name, they will be mapped to the same digiKam tag (!).
* Picasa person albums and face tags => digiKam person/face tags
    - Note that Picasa has a function (buried in the "Tools" menu) to export face tags (including positions) to the XMP
      metadata, which removes them from the `.picasa.ini` file (so this script won't do anything). digiKam is able to
      import these tags properly. In fact, you could run this Picasa feature on all your photos (which takes forever and
      touches every single file on disk, which might not be desirable) as an alternative way of migrating your face
      tags.

## Where to find `contacts.xml`?

* Can be found at `%LocalAppData%\Google\Picasa2\contacts\contacts.xml`
* Also can be obtained from performing a backup operation from within Picasa.  It will be in the backup location as
  `$Application Data\Google\Picasa2\contacts\backup.xml`

## Installation

Clone the repository and `cd` into it.
Make sure you have Python 3.10 or newer installed.
Install `pip3 install psutil`. On Windows, also `pip3 install pywin32`.

## Suggested usage

This script writes into the digiKam database. If you already have photos in digiKam, you should *at least* make a backup. 
Furthermore, testing shows this script works best when writing into an "empty" digiKam instance.  If you already have 
faces identified prior to running this script, you might get duplicate entries if the digiKam name does not match the name 
this script found.

You may also want to make a backup of the photo directories, though the script doesn't write there. Depending on your 
metadata sync settings in digiKam, digiKam itself may (or not) write some of the added metadata to EXIF tags in your photos.

0. Optional: As this is your last chance to make edits in Picasa that will also be reflected in digiKam, you may want to
   do some cleanups there:
    * Delete unnecessary albums and tags.
    * Go over the detected faces in the "Unknown" folder, as well as the suggestions.
1. Open digiKam. If it shows a first-start wizard, do NOT add your photos yet (there's a bug/feature that makes it not
   determine every image's size then, but this script needs the sizes).
2. Make sure you're using an SQLite database (menu "Settings -> Configure digiKam -> Database") and note its path.
3. Add your photo directory under "Root Album Folders" (menu "Settings -> Configure digiKam -> Collections"). If you
   have multiple, you must repeat this and the following steps for each root directory separately.
4. Wait for the "Find new items" job to complete (see progress bar at the bottom, wait until it says "No active process"
   there). You should now see all your photos in digiKam already, but without their stars and tags.
5. Execute a dry run. Under Linux, it might look sth like this:
   ```bash
   ./main.py --dry_run \
       --photos_dir='/home/user/Pictures' \
       --digikam_db='/home/user/snap/digikam/common/digikam4.db' \
       --contacts='/mnt/WinDrive/Users/user/AppData/Local/Google/Picasa2/contacts/contacts.xml'
   ```
   And when using the Windows Command Prompt (cmd), it might look like this:
   ```cmd
   python main.py --dry_run ^
       --photos_dir="C:\Users\user\Pictures" ^
       --digikam_db="C:\Users\user\Pictures\digikam4.db" ^
       --contacts="%LocalAppData%\Google\Picasa2\contacts\contacts.xml"
   ```
   In this command, `--photos_dir` must point to the same directory you configured in step 3 above, or a sub-directory
   thereof, and `--digikam_db` must point to the `digikam4.db` file under the directory configured in step 2 above.  
   `--contacts` is optional but highly recommended.
6. Make sure there were no errors, and take a look at relevant-looking warnings. Debug if necessary.  Sometimes the .ini 
   file is corrupted (probably due to Picasa crashing in the middle of updating an .ini file) -- you will need to 
   edit the .ini file in such cases)
7. Close digiKam (to prevent concurrent access to the database).
8. Execute the same command without `--dry_run` to carry out the migration.
9. Open digiKam again and do some spot checks to make sure the migration worked as intended.  Note: digiKam may have 
    already detected faces during the initial library scan -- in this case you may end up with overlapping face 
    rectangles.  If this migration started from a "clean" digiKam, you can just move all the "Unknown" faces to 
    "Ignore", otherwise it may take some time to manually clean up from within digiKam (or by editing digikam4.db using
    an SQL client).
10. If you want, you can now run digiKam's face detection to detect faces that Picasa hadn't detected or that were still
    in the "Unknown" folder in Picasa.

## Operation Details

The script writes to the `digikam4.db` file and creates a backup.  However it is also recommended you make a backup too.  

`contacts.xml` usually contains more accurate name information, so locate and provide the file path to it if possible.  

In large old collections, there may be some inconsistencies between .ini files due to crashes in Picasa, manual moving, 
etc.  A lot of inconsistencies can be resolved by using the `contacts.xml` file.  If no `contacts.xml` is available, this 
script tries to work around some of these issues.  For example:

* In the rare instance where a face was identified in the .ini file without a corresponding name in either .ini or 
  `contacts.xml`, this script generates a name using the hashed contact ID in the form of
  `.NoName-[hashed-contact-id]-from-rect64`. E.g. `.NoName-da61ef7edfd692c5-from-rect64`

* In another rare instance where a face was identified multiple times in .ini files, this script generates a guessed name
  using a concatenation of all the sorted names found separated by `|`.  E.g. `Marcia|Marsha|Marshia|`
