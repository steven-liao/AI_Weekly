"""Image generation — multiple providers with free fallback options."""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class ImageGenerator:
    """Generates images for articles. Deduplicates by image_prompt hash to avoid
    generating the same image twice (when the same article appears in multiple rankings).

    Supported providers:
      - disabled:      No image generation, returns without image_path
      - tongyi:        通义万相 via DashScope (¥0.06/image)
      - pollinations:  Free, no API key needed (may be slow/unstable in mainland China)
      - local_sd:      Free, requires GPU + SD WebUI running locally
    """

    def __init__(self, config):
        self.provider = config.images.provider
        self.tongyi_model = config.images.tongyi_model
        self.tongyi_size = config.images.tongyi_size
        self.sd_url = config.images.local_sd_url
        self._generated: dict[str, str] = {}  # prompt_hash → local_path

    def generate_all(
        self, articles_with_prompts: list[dict], output_dir: str,
        max_retries: int = 2,
    ) -> list[dict]:
        """Generate images for all articles, skipping duplicates.

        Each article dict should have: article_id, image_prompt
        Returns the same list with image_path set.
        """
        if self.provider == "disabled":
            logger.info("Image generation disabled (provider=disabled)")
            return articles_with_prompts

        output_path = Path(output_dir) / "images"
        output_path.mkdir(parents=True, exist_ok=True)

        for i, art in enumerate(articles_with_prompts):
            prompt = art.get("image_prompt", "")
            prompt_hash = self._hash_prompt(prompt)

            if prompt_hash in self._generated:
                art["image_path"] = self._generated[prompt_hash]
                logger.debug(f"Image {i+1}: reusing cached {art['image_path']}")
                continue

            filename = f"{i+1:02d}_{art.get('article_id', 'unknown')}.png"
            filepath = str(output_path / filename)

            try:
                self._generate_with_retry(prompt, filepath, max_retries)
                art["image_path"] = filepath
                self._generated[prompt_hash] = filepath
                logger.info(f"Image {i+1}/'len({articles_with_prompts}): generated {filename}")
            except Exception as e:
                logger.error(f"Image {i+1} failed: {e}")
                art["image_path"] = self._placeholder(filepath)

        return articles_with_prompts

    def _generate_with_retry(self, prompt: str, output_path: str, max_retries: int):
        """Try primary method."""
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                if self.provider == "tongyi":
                    return self._generate_tongyi(prompt, output_path)
                elif self.provider == "pollinations":
                    return self._generate_pollinations(prompt, output_path)
                elif self.provider == "local_sd":
                    return self._generate_local_sd(prompt, output_path)
                else:
                    raise ValueError(f"Unknown image provider: {self.provider}")
            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
        raise last_error or RuntimeError("Image generation failed")

    def _generate_tongyi(self, prompt: str, output_path: str):
        """通义万相 via DashScope API."""
        from dashscope import ImageSynthesis

        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("DASHSCOPE_API_KEY not set")

        # Enhance prompt for tech-news style
        full_prompt = (
            f"{prompt}, high quality, 4k, clean composition, minimalist, "
            f"professional, modern tech aesthetic"
        )

        response = ImageSynthesis.call(
            api_key=api_key,
            model=self.tongyi_model,
            prompt=full_prompt,
            n=1,
            size=self.tongyi_size,
        )

        if response.status_code == 200:
            img_url = response.output.results[0].url
            # Download
            img_data = httpx.get(img_url, timeout=60).content
            with open(output_path, "wb") as f:
                f.write(img_data)
        else:
            raise RuntimeError(f"通义万相 error: {response.message} (code={response.status_code})")

    def _generate_pollinations(self, prompt: str, output_path: str):
        """Pollinations.ai — free, no API key, simply GET an image URL."""
        import urllib.parse

        encoded = urllib.parse.quote(prompt[:500])
        img_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"

        resp = httpx.get(img_url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)

    def _generate_local_sd(self, prompt: str, output_path: str):
        """Local Stable Diffusion WebUI API."""
        import io
        import base64
        from PIL import Image

        payload = {
            "prompt": f"{prompt}, high quality, 4k, clean composition, minimalist, modern",
            "negative_prompt": "text, watermark, letters, signatures, people, faces, blurry, distorted",
            "steps": 20,
            "width": 1024,
            "height": 1365,  # 3:4 portrait for Xiaohongshu
            "cfg_scale": 7,
        }
        resp = httpx.post(f"{self.sd_url}/sdapi/v1/txt2img", json=payload, timeout=180)
        resp.raise_for_status()
        img_data = base64.b64decode(resp.json()["images"][0])
        Image.open(io.BytesIO(img_data)).save(output_path, "PNG")

    @staticmethod
    def _hash_prompt(prompt: str) -> str:
        import hashlib
        return hashlib.md5(prompt.encode()).hexdigest()

    @staticmethod
    def _placeholder(filepath: str) -> str:
        """Create a simple placeholder image when generation fails."""
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1024, 1024), color=(30, 30, 60))
        draw = ImageDraw.Draw(img)
        draw.text((100, 480), "AI Weekly\nImage Unavailable", fill=(180, 180, 220))
        img.save(filepath, "PNG")
        return filepath


def create_image_generator(config) -> ImageGenerator:
    return ImageGenerator(config)
