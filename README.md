# Job Pack Planner — initial Byte-Me version

Local, rules-based preparation of Forms Mobile Electrical Services Job Pack XML files. No AI service is used.

## Install on Unraid

1. Copy this folder to `/mnt/user/appdata/job-pack-planner` on Byte-Me.
2. Open an Unraid terminal in that folder.
3. Run `docker compose up -d --build`.
4. Open `http://192.168.1.187:1976`.

## First use

1. Under **Forms Mobile template**, upload one of your completed Electrical Services Job Pack XML files. The app immediately empties every record value before saving it as the local master template.
2. Import one or more small Booking Alert XML files.
3. Select the booking date. Set **Leave home** at the top of the timeline, the job arrival/departure times, and **Return home** at the bottom, then press **Save day**.
4. Press **Share prepared XML**. On Android this opens the native share sheet when supported; otherwise the file downloads.
5. Open the prepared XML in Forms Mobile and complete findings, job status, photos and signatures normally.

The prepared pack copies the engineers from the booking's **A&A Resources** field. Vehicle registrations are ignored; the first two people become **Lead Engineer** and **Engineer 2**. It also applies the cover details, repeated job/date/address fields, common safety answers, N/A values and the standard hazard controls seen consistently in the completed examples.

The site/customer representative is set to **SM**. When a prepared XML is saved, the app uses the site postcode to make a best-effort lookup for the nearest OpenStreetMap hospital marked as providing emergency services. The result is cached locally; if the lookup is unavailable or has no suitable result, the field is set to **Hospital**.

## Shared folder import

The app can manually scan a specific Unraid share. Add this to the `.env` file beside `docker-compose.yml`:

```env
JOB_PACK_SHARE_PATH=/mnt/user/JobPackPlanner
```

The scanner checks the configured share and all folders beneath it. It automatically recognises small Booking Alert XML files and full completed Job Pack XML examples, so no special folder structure or separate template upload is required. Open **Settings** and press **Scan shared folder now**. Existing jobs keep their edited timeline times when the same booking file is scanned again.

There is no Outlook integration, Microsoft login, background watcher or scheduled task. Files are only read when you upload them or press the shared-folder scan button.

## Important initial-version limitation

Test generated XML with Forms Mobile and the company workflow using a non-critical copy before relying on it. Forms Mobile compatibility is the next validation milestone. Route optimisation and detected office/collection stops are planned after XML round-trip compatibility is confirmed.

All data is stored in the local `data` directory. Do not expose port 1976 directly to the internet.

## Install as a Chrome app

Open the HTTPS address in Chrome, use the install icon in the address bar (or **Menu → Cast, save and share → Install page as app**) and choose **Install**. The installed app uses its own Job Pack Planner icon, standalone window, matching splash colour and full branded header.
