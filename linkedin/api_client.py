"""Low-level LinkedIn API wrapper — REST Posts API only."""

import asyncio
import logging
from pathlib import Path
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

LINKEDIN_VERSION = "202601"
REST_BASE = "https://api.linkedin.com/rest"
V2_BASE = "https://api.linkedin.com/v2"


class LinkedInAPIClient:
    """Wraps LinkedIn API calls for creating and managing posts.

    Uses the REST Posts API (/rest/posts) exclusively. Special characters
    are escaped before sending to prevent LinkedIn's silent truncation.
    """

    # Characters that LinkedIn interprets as markdown/formatting.
    # Escaping them prevents silent truncation — matches Postiz's fixText().
    _ESCAPE_CHARS = ['\\', '<', '>', '#', '~', '_', '|', '[', ']', '*', '(', ')', '{', '}', '@']

    def __init__(self, access_token: str):
        self.access_token = access_token

    def _escape_for_linkedin(self, text: str) -> str:
        """Escape special chars that LinkedIn interprets as formatting.

        Without escaping, LinkedIn's API may silently truncate content
        when it encounters characters it tries to parse as markdown.
        """
        for ch in self._ESCAPE_CHARS:
            text = text.replace(ch, f'\\{ch}')
        return text

    def _rest_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": LINKEDIN_VERSION,
            "Content-Type": "application/json",
        }

    async def create_text_post(self, person_urn: str, commentary: str) -> dict:
        """Create a text-only post on behalf of the authenticated user.

        Uses REST Posts API only (no UGC fallback — UGC has a 1300 char limit
        and different truncation behavior).
        Returns dict with 'post_urn' on success or 'error' on failure.
        """
        return await self._create_via_rest(person_urn, commentary)

    async def _create_via_rest(self, person_urn: str, commentary: str) -> dict:
        """Create post via REST Posts API (/rest/posts)."""
        # Escape special chars before sending — prevents silent truncation
        commentary = self._escape_for_linkedin(commentary)

        logger.info(
            "Sending to REST API: commentary_length=%d, commentary_bytes=%d",
            len(commentary),
            len(commentary.encode("utf-8")),
        )

        payload = {
            "author": person_urn,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{REST_BASE}/posts",
                json=payload,
                headers=self._rest_headers(),
                timeout=30.0,
            )

            logger.warning(
                "REST POST response: status=%s, headers=%s, body=%s",
                response.status_code,
                dict(response.headers),
                response.text[:500] if response.text else "(empty)",
            )

            if response.status_code in (200, 201):
                post_urn = response.headers.get("x-restli-id", "")
                logger.warning(
                    "Post created via REST API: urn=%s, sent_chars=%d, sent_bytes=%d, "
                    "sent_newlines=%d, first_80=%r, last_80=%r",
                    post_urn,
                    len(commentary),
                    len(commentary.encode("utf-8")),
                    commentary.count("\n"),
                    commentary[:80],
                    commentary[-80:],
                )
                return {
                    "success": True,
                    "post_urn": post_urn,
                    "status_code": response.status_code,
                    "chars_sent": len(commentary),
                }

            logger.warning(
                "REST Posts API failed: %s %s",
                response.status_code,
                response.text,
            )
            return {
                "success": False,
                "error": response.text,
                "status_code": response.status_code,
            }

    async def create_image_post(
        self, person_urn: str, commentary: str, image_path: str
    ) -> dict:
        """Create a post with an image on LinkedIn.

        Steps: 1) Initialize upload, 2) Upload image binary, 3) Create post with image URN.
        Falls back to text-only post if image upload fails.
        """
        # Resolve the image file on disk
        file_path = Path("dashboard" + image_path)
        if not file_path.exists():
            logger.warning("Image file not found: %s — falling back to text post", file_path)
            return await self.create_text_post(person_urn, commentary)

        image_bytes = file_path.read_bytes()
        content_type = "image/png" if file_path.suffix == ".png" else "image/jpeg"

        # Step 1: Initialize upload via REST API
        init_payload = {
            "initializeUploadRequest": {
                "owner": person_urn,
            }
        }
        async with httpx.AsyncClient() as client:
            init_resp = await client.post(
                f"{REST_BASE}/images?action=initializeUpload",
                json=init_payload,
                headers=self._rest_headers(),
                timeout=30.0,
            )

            if init_resp.status_code not in (200, 201):
                logger.warning(
                    "Image upload init failed (%s): %s — falling back to text post",
                    init_resp.status_code,
                    init_resp.text,
                )
                return await self.create_text_post(person_urn, commentary)

            try:
                init_data = init_resp.json()
                upload_url = init_data["value"]["uploadUrl"]
                image_urn = init_data["value"]["image"]
            except (ValueError, KeyError) as e:
                logger.warning("Image upload init returned invalid data: %s", e)
                return await self.create_text_post(person_urn, commentary)

            # Step 2: Upload the image binary
            upload_headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": content_type,
            }
            upload_resp = await client.put(
                upload_url,
                content=image_bytes,
                headers=upload_headers,
                timeout=60.0,
            )

            if upload_resp.status_code not in (200, 201):
                logger.warning(
                    "Image binary upload failed (%s): %s — falling back to text post",
                    upload_resp.status_code,
                    upload_resp.text,
                )
                return await self.create_text_post(person_urn, commentary)

            # Step 3: Create post with the image
            commentary = self._escape_for_linkedin(commentary)
            logger.info(
                "Creating image post: commentary_length=%d, image_urn=%s",
                len(commentary),
                image_urn,
            )
            post_payload = {
                "author": person_urn,
                "commentary": commentary,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "content": {
                    "media": {
                        "id": image_urn,
                    }
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }

            post_resp = await client.post(
                f"{REST_BASE}/posts",
                json=post_payload,
                headers=self._rest_headers(),
                timeout=30.0,
            )

            logger.warning(
                "IMAGE POST response: status=%s, headers=%s, body=%s",
                post_resp.status_code,
                dict(post_resp.headers),
                post_resp.text[:500] if post_resp.text else "(empty)",
            )

            if post_resp.status_code in (200, 201):
                post_urn = post_resp.headers.get("x-restli-id", "")
                logger.warning(
                    "Image post created via REST API: urn=%s, sent_chars=%d, "
                    "sent_newlines=%d, first_80=%r, last_80=%r",
                    post_urn,
                    len(commentary),
                    commentary.count("\n"),
                    commentary[:80],
                    commentary[-80:],
                )
                return {
                    "success": True,
                    "post_urn": post_urn,
                    "status_code": post_resp.status_code,
                }

            logger.error(
                "Image post creation failed (%s): %s",
                post_resp.status_code,
                post_resp.text,
            )
            return {
                "success": False,
                "error": post_resp.text,
                "status_code": post_resp.status_code,
            }

    async def create_video_post(
        self, person_urn: str, commentary: str, video_path: str
    ) -> dict:
        """Create a post with a video or GIF on LinkedIn.

        Steps: 1) Initialize upload, 2) Upload binary, 3) Wait for processing,
        4) Create post with video URN.
        Falls back to text-only post if video upload fails.
        """
        file_path = Path("dashboard" + video_path)
        if not file_path.exists():
            logger.warning("Video file not found: %s — falling back to text post", file_path)
            return await self.create_text_post(person_urn, commentary)

        video_bytes = file_path.read_bytes()
        file_size = len(video_bytes)
        suffix = file_path.suffix.lower()

        # Step 1: Initialize video upload
        init_payload = {
            "initializeUploadRequest": {
                "owner": person_urn,
                "fileSizeBytes": file_size,
                "uploadCaptions": False,
                "uploadThumbnail": False,
            }
        }
        async with httpx.AsyncClient() as client:
            init_resp = await client.post(
                f"{REST_BASE}/videos?action=initializeUpload",
                json=init_payload,
                headers=self._rest_headers(),
                timeout=30.0,
            )

            if init_resp.status_code not in (200, 201):
                logger.warning(
                    "Video upload init failed (%s): %s — falling back to text post",
                    init_resp.status_code,
                    init_resp.text,
                )
                return await self.create_text_post(person_urn, commentary)

            try:
                init_data = init_resp.json()
                upload_url = init_data["value"]["uploadInstructions"][0]["uploadUrl"]
                video_urn = init_data["value"]["video"]
            except (ValueError, KeyError, IndexError) as e:
                logger.warning("Video upload init returned invalid data: %s", e)
                return await self.create_text_post(person_urn, commentary)

            # Step 2: Upload video binary
            content_type = {
                ".gif": "image/gif",
                ".mp4": "video/mp4",
                ".webm": "video/webm",
                ".mov": "video/quicktime",
            }.get(suffix, "video/mp4")

            upload_headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": content_type,
            }
            upload_resp = await client.put(
                upload_url,
                content=video_bytes,
                headers=upload_headers,
                timeout=120.0,
            )

            if upload_resp.status_code not in (200, 201):
                logger.warning(
                    "Video binary upload failed (%s): %s — falling back to text post",
                    upload_resp.status_code,
                    upload_resp.text,
                )
                return await self.create_text_post(person_urn, commentary)

            # Step 3: Wait for LinkedIn to finish processing the video
            ready = await self._wait_for_video_ready(client, video_urn)
            if not ready:
                logger.warning("Video processing timed out — falling back to text post")
                return await self.create_text_post(person_urn, commentary)

            # Step 4: Create post with the video
            commentary = self._escape_for_linkedin(commentary)
            logger.info(
                "Creating video post: commentary_length=%d, video_urn=%s",
                len(commentary),
                video_urn,
            )
            post_payload = {
                "author": person_urn,
                "commentary": commentary,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "content": {
                    "media": {
                        "id": video_urn,
                    }
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }

            post_resp = await client.post(
                f"{REST_BASE}/posts",
                json=post_payload,
                headers=self._rest_headers(),
                timeout=30.0,
            )

            if post_resp.status_code in (200, 201):
                post_urn = post_resp.headers.get("x-restli-id", "")
                logger.info("Video post created via REST API: %s", post_urn)
                return {
                    "success": True,
                    "post_urn": post_urn,
                    "status_code": post_resp.status_code,
                }

            logger.error(
                "Video post creation failed (%s): %s",
                post_resp.status_code,
                post_resp.text,
            )
            return {
                "success": False,
                "error": post_resp.text,
                "status_code": post_resp.status_code,
            }

    async def _wait_for_video_ready(
        self, client: httpx.AsyncClient, video_urn: str, max_wait: int = 120
    ) -> bool:
        """Poll LinkedIn until the uploaded video is ready for posting.

        Returns True if video is available, False if timed out.
        """
        encoded = quote(video_urn, safe="")
        elapsed = 0
        interval = 5  # seconds between polls

        while elapsed < max_wait:
            try:
                resp = await client.get(
                    f"{REST_BASE}/videos/{encoded}",
                    headers=self._rest_headers(),
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    status = resp.json().get("status", "")
                    if status == "AVAILABLE":
                        logger.info("Video %s is ready (took %ds)", video_urn, elapsed)
                        return True
                    if status in ("PROCESSING_FAILED", "DELETED"):
                        logger.error("Video %s failed with status: %s", video_urn, status)
                        return False
            except Exception as e:
                logger.warning("Video status check failed: %s", e)

            await asyncio.sleep(interval)
            elapsed += interval

        logger.error("Video %s not ready after %ds", video_urn, max_wait)
        return False

    async def get_post(self, post_urn: str) -> dict | None:
        """Retrieve a post by its URN."""
        encoded_urn = quote(post_urn, safe="")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{REST_BASE}/posts/{encoded_urn}",
                headers=self._rest_headers(),
                timeout=15.0,
            )
            if response.status_code == 200:
                return response.json()
            logger.error("Failed to get post %s: %s", post_urn, response.status_code)
            return None

    async def fetch_author_posts(self, person_urn: str, count: int = 100) -> list[dict]:
        """Fetch the authenticated user's post history from LinkedIn.

        Returns a list of dicts with post URN, text, created timestamp, etc.
        Uses the REST Posts API with q=author.
        """
        all_posts = []
        start = 0
        batch = min(count, 50)  # LinkedIn max per page is 50

        async with httpx.AsyncClient() as client:
            while start < count:
                params = {
                    "author": person_urn,
                    "q": "author",
                    "count": batch,
                    "start": start,
                    "sortBy": "LAST_MODIFIED",
                }
                resp = await client.get(
                    f"{REST_BASE}/posts",
                    params=params,
                    headers=self._rest_headers(),
                    timeout=30.0,
                )

                if resp.status_code != 200:
                    logger.warning(
                        "Failed to fetch posts (start=%d): %s %s",
                        start, resp.status_code, resp.text[:200],
                    )
                    break

                data = resp.json()
                elements = data.get("elements", [])
                if not elements:
                    break

                for post in elements:
                    post_urn = post.get("id", "")
                    commentary = post.get("commentary", "")
                    created_at = post.get("createdAt", 0)
                    lifecycle = post.get("lifecycleState", "")

                    all_posts.append({
                        "urn": post_urn,
                        "content": commentary,
                        "created_at": created_at,
                        "lifecycle_state": lifecycle,
                        "visibility": post.get("visibility", ""),
                        "has_media": "content" in post,
                    })

                start += len(elements)
                if len(elements) < batch:
                    break

        logger.info("Fetched %d posts from LinkedIn", len(all_posts))
        return all_posts

    async def fetch_post_social_counts(self, post_urn: str) -> dict[str, int]:
        """Fetch likes, comments, shares for a single post URN.

        Uses the socialActions endpoint and socialMetadata as fallback.
        """
        encoded = quote(post_urn, safe="")

        async with httpx.AsyncClient() as client:
            # Try socialMetadata first (single call)
            meta_resp = await client.get(
                f"{REST_BASE}/socialMetadata/{encoded}",
                headers=self._rest_headers(),
                timeout=15.0,
            )
            if meta_resp.status_code == 200:
                d = meta_resp.json()
                return {
                    "likes": d.get("totalLikes", d.get("likeCount", 0)),
                    "comments": d.get("totalComments", d.get("commentCount", 0)),
                    "shares": d.get("totalShares", d.get("shareCount", 0)),
                }

            # Fallback: individual socialActions
            likes = 0
            comments = 0
            for action in ("likes", "comments"):
                try:
                    r = await client.get(
                        f"{V2_BASE}/socialActions/{encoded}/{action}?count=0",
                        headers={
                            "Authorization": f"Bearer {self.access_token}",
                            "X-Restli-Protocol-Version": "2.0.0",
                            "LinkedIn-Version": LINKEDIN_VERSION,
                        },
                        timeout=15.0,
                    )
                    if r.status_code == 200:
                        total = r.json().get("paging", {}).get("total", 0)
                        if action == "likes":
                            likes = total
                        else:
                            comments = total
                except Exception:
                    pass

            return {"likes": likes, "comments": comments, "shares": 0}

    async def delete_post(self, post_urn: str) -> bool:
        """Delete a post by its URN."""
        encoded_urn = quote(post_urn, safe="")
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{REST_BASE}/posts/{encoded_urn}",
                headers=self._rest_headers(),
                timeout=15.0,
            )
            if response.status_code == 204:
                logger.info("Post deleted: %s", post_urn)
                return True
            logger.error(
                "Failed to delete post %s: %s", post_urn, response.status_code
            )
            return False
