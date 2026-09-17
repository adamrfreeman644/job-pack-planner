# Job Pack Planner

A self-hosted day planner for preparing Forms Mobile Electrical Services Job Pack XML files from Booking Alert XML files.

Import bookings, set arrival and departure times, and download a pre-filled XML pack for each job. The app uses fixed rules rather than an AI service. It runs with Flask, SQLite and Docker, and is set up for Unraid.

## Features

- Import one or more booking XML files from Settings.
- Scan a shared folder and its subfolders for bookings and completed Job Pack examples.
- View bookings by date, inspect the work description and open a site's postcode in Google Maps.
- Save job arrival and departure times, plus leave-home and return-home times.
- Download a prepared XML file and copy its job number to the clipboard when the browser allows it.
- Use engineers from each booking, with a configurable fallback.
- Look up a nearby emergency hospital when exporting a pack.
- Open the app in a standalone browser window on supported browsers.
- View Immich photos taken during a job in a clean, white fullscreen viewer.
- Reorder a day by dragging job cards or using mobile-friendly up/down controls.
- Open the current day as a multi-stop Google Maps route without an API key.
- Plan a day with OpenRouteService using least-driving or furthest-first ordering, pickups/drop-offs and a full-screen map preview.

## Install with Docker on Unraid

You need Docker with Docker Compose and a copy of this repository.

1. Copy or clone the repository to `/mnt/user/appdata/job-pack-planner`.
2. Create a folder for your booking XML files and completed Job Pack examples, such as `/mnt/user/JobPackPlanner`.
3. In the repository folder, create a `.env` file containing:

   ```env
   JOB_PACK_SHARE_PATH=/mnt/user/JobPackPlanner
   ```

4. Open a terminal in the repository folder and run:

   ```sh
   docker compose up -d --build
   ```

5. Open `http://<server-ip>:1976` in your browser. For the Byte-Me installation, the existing address is `http://192.168.1.187:1976`.

The Compose configuration mounts `./data` as `/data` and the configured import folder as `/imports`. If `JOB_PACK_SHARE_PATH` is omitted, imports use `./shared` beside the Compose file. After changing the path in `.env`, run `docker compose up -d` to apply it.

## First use

1. Put at least one completed Electrical Services Job Pack XML example in the configured shared folder. This is required before exporting a pack.
2. Open **Settings → Scan shared folder now**. The app selects the most recently modified completed example and clears the first record's field text values before saving it as the master template.
3. Add Booking Alert XML files to the shared folder and scan again, or use **Settings → Choose booking XML files** to import them manually.
4. Return to the planner and select the booking date.
5. Set **Leave home**, each job's **Arrive** and **Leave** times, and **Return home**. Press **Save day** before exporting.
6. Press **Save XML** on a job. The browser downloads `<job-number>.xml` and attempts to copy the job number to the clipboard.
7. Open the XML in Forms Mobile, review the pre-filled values, and complete the findings, job status, photos and signatures.

**Save XML** uses the last saved times; it does not save unsaved timeline edits. Leave-home and return-home times are shared settings across dates, while arrival and departure times are stored per job.

## Imports and templates

The shared-folder scanner checks files ending in `.xml` recursively. It treats the first record with at least 100 fields as a completed Job Pack example; files with fewer fields are passed to the booking importer. If several examples exist, the most recently modified one replaces the master template on each scan.

Bookings are matched by job number. Re-importing a booking updates its details and date while preserving its edited arrival time, departure time and position. Booking dates are read as `DD-MM-YYYY`; an unrecognised date falls back to the current date on the server.

The current Settings page provides booking upload and shared-folder scanning. Install the master template through the shared-folder scan.

Files are imported only when you upload them or press **Scan shared folder now**. Settings reads the folder to show file counts, but there is no automatic import, email integration, background watcher or scheduled task.

## What the prepared XML contains

The app fills matching template fields with:

- Job number, booking ID, client, customer reference, site address, contact information and work required.
- The selected date and saved travel and site times. Travel times are derived from the previous job's departure and the next job's arrival, with home times used at the ends of the day.
- Engineers from **A&A Resources**, or **Settings → Default resources** when that booking field is empty. Entries matching the supported UK vehicle-registration pattern are ignored; the first two recognised people supply first names for **Lead Engineer** and **Engineer 2**.
- Fixed defaults, including division `AM`, site/customer representative `SM` and a default RAMS number of `010203`.
- Preset safety answers, N/A values, hazard selections and controls.

These are fixed preparation rules, not an assessment of the work or site conditions. Review the defaults in Forms Mobile for each job.

### Hospital lookup

On export, the app sends the site postcode to Postcodes.io, then queries OpenStreetMap through the Overpass API for emergency hospital locations within 80 km. It selects the nearest named result by straight-line distance and includes its postcode when available.

Successful results are cached locally by site postcode. If the lookup fails or finds no suitable result, the field contains `Hospital`. The result is a best-effort suggestion and should be checked for the job.

## Day route planning

Route ordering is kept in one place: press **Plan day** for the full-screen planner. The main timeline stays focused on job times and Job Pack actions.

The daily route planner offers three clear levels: **Auto** chooses the least-driving route, **Semi-auto** starts at the furthest job and works home, and **Manual** lets you set the job order with up/down controls. Enter each colleague once with their name and home address or postcode. The planner automatically places their pickup before every job and their matching drop-off after every job. The day always starts and finishes at your saved home address. Collections are saved for that date and included in routing, but do not create Job Packs. Review the map, ordered stops, mileage and estimated driving time, then press **Save and apply route**.

Automatic planning uses the free OpenRouteService public API:

1. Create an account at **openrouteservice.org**.
2. Create an API key in its dashboard.
3. Save your home/start address and key under **Settings → Day route planning**.
4. Press **Plan route**, choose a mode, add any collections and press **Arrange route**.

The key stays in `planner.db` and is excluded from browser state. Geocoded locations are cached locally to reduce API use. A route supports up to 25 combined jobs, pickups and drop-offs.

**Start route** sends the saved order to the normal Google Maps website/app. Google is used only for navigation, so no Google API key or billing account is required.

## Job photos with Immich

Open **Settings → Job photos · Immich** and enter:

- **Immich address:** the address reachable from the planner container, such as `http://your-immich-server:2283`. A trailing `/api` is optional.
- **API key:** create a key in Immich with `asset.read` and `asset.view` permissions. Some Immich preview responses redirect to the original image and also require `asset.download`. Use **Save and test connection** to check search and preview access.
- **Job timezone:** defaults to `Europe/London`, including daylight-saving changes.
- **Minutes before and after each job:** an optional allowance from 0 to 120 minutes, defaulting to 0.
- **Check for new photos:** every 5 minutes by default, or choose a different interval or manual checks only.

The API key is saved in the planner's local database and is never returned to the browser or included in photo URLs. Leaving the key blank keeps the saved key. Changing the server address requires a new key; **Remove saved API key** disconnects access. Protect database backups because they contain this credential. The existing trusted-network access model applies: people who can open the planner can view the job photos made available by that Immich account.

### Use the viewer

1. Save the job's arrival and departure times with **Save day**.
2. Click **Photos** beside **Description** and **Save XML**. The planner checks Immich and opens the first matching photo.
3. Tap anywhere in the left half to go back, or the right half to go forward. Arrow keys work too.
4. A plain **Leave photo viewer** screen sits before the first and after the last photo. Tap either half on that screen to return to the planner, or press Escape at any time.

Photos appear oldest first, fitted completely inside a white screen with no visible buttons, captions or counters. The viewer uses Immich's browser-compatible preview images; their resolution depends on the Immich server's preview settings. Browsers that allow the Fullscreen API hide browser chrome. Otherwise the viewer fills the page; use an installed standalone app for the cleanest screenshots. Loading and error messages appear only when a photo cannot yet be displayed.

**Check photos** in the planner header refreshes photo counts for the selected day. Automatic checks run while the planner page is visible, and pause while the viewer is open. The photo sequence stays fixed during viewing; reopen it to include newly uploaded photos. No scheduled server process runs when the planner is closed.

Matching uses Immich's capture timestamp (`fileCreatedAt`), not upload time, and includes the saved arrival and departure instants. A departure earlier than arrival means the following day; identical times must be corrected. Photos with missing or incorrect capture metadata may not match. Videos and trashed assets are excluded. Matching is by time only, so unrelated photos taken during the same window can also appear. Every results page is checked; failed checks report an error rather than silently showing a partial result.

The integration uses Immich's [metadata search](https://github.com/immich-app/immich/blob/main/server/src/controllers/search.controller.ts) and [photo preview](https://github.com/immich-app/immich/blob/main/server/src/controllers/asset-media.controller.ts) APIs. Search and photo content pass through the planner server; the browser does not connect directly to Immich.

### Update an existing installation

Pull the latest repository files, then run `docker compose up -d --build` in the installation folder. Refresh the planner page and configure Immich in Settings. Existing bookings and the master template remain in `data`.

### Run the tests

With the requirements installed, run `python -m unittest discover -s tests -v`. Tests use temporary databases and mocked Immich responses; they do not need a real API key or photo library.

## Data and access

The host's `data` folder contains:

| File | Contents |
| --- | --- |
| `planner.db` | Bookings, saved times, settings (including the Immich key), cached hospital results and the latest photo matches per job |
| `master.xml` | The prepared master template |

Back up this folder to preserve the planner's data. Original files in the import folder are read without being changed.

The app has no built-in sign-in. Use it on a trusted network and do not expose port 1976 directly to the internet. XML preparation runs on your server; hospital lookup requires internet access, and postcode links open Google Maps.

## Install as a browser app

For a remote server, use an HTTPS address configured separately from the supplied Docker setup. Open it in a supported browser and use the browser's install option when available.

The manifest provides the app name, icons, colours and standalone display. The service worker caches static assets only; the planner still needs a connection to the server to load bookings, save changes and export XML.

## Current limitations

- Forms Mobile XML round-trip compatibility still needs validation with the company workflow. Test a non-critical copy before relying on generated packs.
- Route optimisation and automatic office or collection stops are not implemented.
- Safety answers and hazard controls are presets that require review for each job.
- Browser clipboard access depends on browser support and permissions; XML download can still work if copying the job number fails.
