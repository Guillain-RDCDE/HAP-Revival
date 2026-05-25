# Recipe: Decompile the Sony HDD Audio Remote Android APK

The official `com.sony.HAP.HDDAudioRemote` Android app contains the **complete method dictionary** the HAP family understands — every name, every version, every JSON parameter shape Sony has wired through their own iOS/Android client.

**Nobody has ever publicly decompiled it.** Doing so is the highest-leverage unblocking work in the whole HAP-Revival project. Estimated effort: one evening.

## What you'll need

- A computer with **8 GB+ RAM** (jadx is JVM-heavy).
- **Java JDK 11 or newer**.
- **apktool 2.9.0+** — https://apktool.org/
- **jadx 1.5.0+** — https://github.com/skylot/jadx (the GUI build is easiest)
- The APK itself.

## Step 1 — Get the APK

Two options:

### Option A: pull from APKMirror (recommended)

- URL: https://www.apkmirror.com/apk/sony-corporation/hdd-audio-remote/hdd-audio-remote-4-3-1-release/
- Version 4.3.1, ~12.88 MB, last updated 2022-12-12, min Android 7.0.
- Verify the SHA-256 of the downloaded file matches what APKMirror displays.

### Option B: pull from your own Android device

If you have an Android device with the app installed:

```bash
adb shell pm path com.sony.HAP.HDDAudioRemote
# Returns: package:/data/app/com.sony.HAP.HDDAudioRemote-XXXXX/base.apk
adb pull /data/app/.../base.apk HDDAudioRemote-4.3.1.apk
```

## Step 2 — Extract the manifest and resources with apktool

```bash
apktool d HDDAudioRemote-4.3.1.apk -o HDDAudioRemote-decoded/
```

This gives you:

- `AndroidManifest.xml` (decoded, human-readable)
- `res/` — all resources including strings.xml
- `smali/` — the Dalvik bytecode (less readable than jadx Java output, but ground truth)
- `assets/` — any bundled JSON, config, or doc files Sony shipped inside the APK

**First thing to look at**: `assets/`. Sony has historically shipped JSON manifests of supported devices and methods as assets in their control apps. If you find files like `device_capabilities.json`, `method_index.json`, anything like that — you may have just struck gold.

## Step 3 — Decompile to readable Java with jadx

```bash
# CLI:
jadx -d HDDAudioRemote-jadx/ HDDAudioRemote-4.3.1.apk

# Or open the GUI and load the APK:
jadx-gui HDDAudioRemote-4.3.1.apk
```

The resulting `HDDAudioRemote-jadx/sources/` tree contains decompiled Java.

## Step 4 — Where to look (high-yield directories)

Based on Sony's other apps (Headphones Connect, Music Center, SongPal):

- `com/sony/HAP/...` — HAP-specific code. **Start here.**
- `com/sony/scalar/...` or `com/sony/songpal/...` — shared ScalarWebAPI code.
- Files named `*Method*.java`, `*Api*.java`, `*Service*.java` — likely API plumbing.
- `*Request.java` / `*Response.java` — DTOs that map directly to JSON shapes.

Grep for:

```bash
grep -r 'getPlayingContentInfo' HDDAudioRemote-jadx/
grep -r '60200' HDDAudioRemote-jadx/
grep -r 'switchNotifications' HDDAudioRemote-jadx/
grep -r '/sony/' HDDAudioRemote-jadx/
grep -r 'audio:track' HDDAudioRemote-jadx/
```

This will surface every API call site. From each one you can read backward to find:

- The method name string.
- The version string (e.g. `"1.2"`).
- The construction of the params array.
- The expected response shape (in the response DTO).

## Step 5 — Produce the catalog update

For each new method you discover, add a row to [`research/api-method-catalog.md`](../research/api-method-catalog.md) with:

- Service
- Method name
- Version found in the APK
- Params shape (Java DTO → JSON)
- Status: `❓` (untested live)

Then test against a real device (run `python tools/api-fuzzer.py --method <name>`) and update the status.

## Legal & ethics

- **The decompiled APK source is Sony's intellectual property.** Do not commit it to this repository, do not redistribute it. The decompilation is fair use for the purpose of **interoperability** — see e.g. EU Directive 2009/24/EC Article 6, U.S. DMCA §1201(f).
- What you may commit: **the extracted constants and method dictionaries** as documentation in our catalog, with attribution noting they were derived from APK analysis. This is documentation of facts (the API shape), not redistribution of Sony's code.
- Do not commit anything that includes Sony's UI assets (icons, strings, images), Sony's proprietary algorithms (DSEE upscaler logic, DSD remastering), or any cryptographic keys.

## Expected timeline

- Step 1 (download): 5 minutes.
- Step 2 (apktool): 1 minute of compute + 30 minutes inspecting the manifest and assets.
- Step 3 (jadx): 10–30 minutes of compute on first run.
- Step 4 (analysis): 2–4 hours of careful reading.
- Step 5 (catalog update + PR): 1–2 hours.

**Total: one evening for someone comfortable reading decompiled Java.**

## If apktool fails

Sony sometimes ships APKs with obfuscation or anti-tampering. If `apktool d` errors:

- Try `apktool d --only-main-classes`.
- Try a more recent apktool version (2.10+).
- Try [APKEditor](https://github.com/REAndroid/APKEditor) as a fallback.

## After analysis

Once you have a catalog of methods from the APK, run `tools/api-fuzzer.py --method <name>` to validate each against a live device. The fuzzer is set up to record what works and what doesn't.

Then open a PR titled `[research] Update API method catalog from HDDAudioRemote 4.3.1 APK analysis`. Tag @Guillain-RDCDE for review.

You will have just done the most impactful single contribution in the history of HAP reverse engineering.
