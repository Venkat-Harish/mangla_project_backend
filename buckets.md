# Mangla Storage Buckets

Supabase Storage on the same project as the database (project ref `rpthhezkrrjtumyqtndz`). The backend reaches it with `SUPABASE_URL` and `SUPABASE_SECRET_KEY` from `.env`, which is git-ignored.

All three buckets are **private**, with no file size limit and no file type restriction set. Files are shown to users through signed URLs.

The backend's Storage code is `packages/storage`: bucket names and folder rules (`storage_config.py` `MEDIA_KINDS`), path checks, signed download and upload URLs. The database stores each file's path inside its bucket; the endpoints that use them are in [docs/End-Points.md](docs/End-Points.md) ("Media files").

A folder in Supabase Storage is part of a file's path. Per-user, per-kitchen and per-dish folders appear when the first file is uploaded under that path, so they don't have to be created in advance. The IDs in folder names are the `uuid` primary keys from the database (see [DATABASE.md](DATABASE.md)).

## How folders get created

**Nothing to do by hand, and no workflow is needed.** Storage has no real folders: a "folder" is just the part of a file's path before the last `/`. Uploading `dishes_pics/<kitchen_id>/<dish_id>/photo1.jpg` makes the `<kitchen_id>` and `<dish_id>` folders appear at that moment, and they vanish once their last file is deleted.

- **New kitchen or new dish:** create nothing in Storage. The kitchen's and dish's folders appear when their first picture is uploaded.
- **New user:** same; `users/<user_id>/` appears with the user's first review photo.
- **Top-level folders** (`users/`, `kitchens/`, `kitchen_display_pics/`, `dishes_pics/`) were made in the dashboard. Each holds a hidden `.emptyFolderPlaceholder` file so it shows while empty; leave that file in place.
- **Why not pre-create folders when a kitchen is created:** an empty folder only exists through a placeholder file, so it would mean extra uploads, extra files to clean up, and a second step that could fail after the kitchen is saved, with no gain.

**Where the backend does need logic:**
- **Building the path:** the backend, not the app, decides the path from the IDs (e.g. `dishes_pics/<kitchen_id>/<dish_id>/<random name>.<ext>`), so files can't land in another kitchen's or user's folder. A random file name avoids two uploads overwriting each other. Built: `packages/storage` `new_path` makes the path for `/media/upload-url`, and `is_in_folder` checks every path before it is saved.
- **Clean-up on delete:** when a dish, kitchen, review or user is deleted, delete the files under its folder too (list the folder, then remove the files). This is the only step that acts on "folders" as a whole. Not built yet: no endpoint deletes these rows today.

## Overview

| Bucket | Folder layout | Contents |
|---|---|---|
| [reviews_photos_and_videos](#reviews_photos_and_videos) | `users/<user_id>/` | Photos and videos users add to their reviews |
| [posts_photos_videos](#posts_photos_videos) | `kitchens/<kitchen_id>/` | Photos and videos posted for a kitchen |
| [dish_and_kitchen_photos_videos](#dish_and_kitchen_photos_videos) | `kitchen_display_pics/<kitchen_id>/`<br>`dishes_pics/<kitchen_id>/<dish_id>/` | Kitchen display pictures and dish images |

---

## reviews_photos_and_videos

Photos and videos that users add when they review something.

```
reviews_photos_and_videos/
└── users/
    └── <user_id>/          one folder per user (users.user_id)
        └── photos and videos from all of that user's reviews
```

- **users/**: holds one folder per user.
- **users/<user_id>/**: every photo and video that user has added to any of their reviews.
- **Database:** their paths (e.g. `users/<user_id>/<file>`) are stored in `all_reviews.images`. A new review gets them from `/orders/review` `images[]`; an existing one from `/review/edit` `add_images[]`.

---

## posts_photos_videos

Photos and videos posted for a kitchen.

```
posts_photos_videos/
└── kitchens/
    └── <kitchen_id>/       one folder per kitchen (all_kitchens.kitchen_id)
        └── photos and videos of all posts for that kitchen
```

- **kitchens/**: holds one folder per kitchen.
- **kitchens/<kitchen_id>/**: every photo or video posted for that kitchen.
- **Database:** no posts table yet.

---

## dish_and_kitchen_photos_videos

The kitchen's display pictures and the images of each dish.

```
dish_and_kitchen_photos_videos/
├── kitchen_display_pics/
│   └── <kitchen_id>/       one folder per kitchen (all_kitchens.kitchen_id)
│       └── display pictures shown when the kitchen is opened
└── dishes_pics/
    └── <kitchen_id>/       one folder per kitchen (all_kitchens.kitchen_id)
        └── <dish_id>/      one folder per dish of that kitchen (all_dishes.dish_id)
            └── images of that dish
```

- **kitchen_display_pics/<kitchen_id>/**: the kitchen's own display pictures, shown when a user opens that kitchen.
- **dishes_pics/<kitchen_id>/<dish_id>/**: images of that one dish. The dish folder sits under the folder of the kitchen that offers it.
- **Database:** dish image paths are stored in `all_dishes.images`. `all_kitchens` has no column for display pictures yet.
