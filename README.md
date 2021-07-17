# picasa2digikam

A script to migrate Picasa metadata from its `.picasa.ini` files (does not require Picasa to be installed and therefore
does not require Windows) to the [digiKam](https://www.digikam.org/) database (does not write into the file system, so
the original files should remain untouched).

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

## Suggested usage

This script writes into the digiKam database. If you already have photos in digiKam, you should *at least* make a
backup. Furthermore, this script has been tested only when writing into an "empty" digiKam instance, so you might get
better results by starting with an empty instance too. You may also want to make a backup of the photo directories,
though the script doesn't write there. Depending on your metadata sync settings in digiKam, digiKam itself may (or not)
write some of the added metadata to EXIF tags in your photos.

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
5. Execute a dry run:
   ```bash
   ./main.py --dry_run \
       --photos_dir='C:\Users\user\...' \
       --digikam_db='C:\Users\user\...\digikam4.db'
   ```
   In this command, `--photos_dir` must point to the same directory you configured in step 3 above, or a sub-directory
   thereof, and `--digikam_db` must point to the `digikam4.db` file under the directory configured in step 2 above.
6. Make sure there were no errors, and take a look at relevant-looking warnings. Debug if necessary.
7. Close digiKam (to prevent concurrent access to the database).
8. Execute the same command without `--dry_run` to carry out the migration.
9. Open digiKam again and do some spot checks to make sure the migration worked as intended.
10. If you want, you can now run digiKam's face detection to detect faces that Picasa hadn't detected or that were still
    in the "Unknown" folder in Picasa.
