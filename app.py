"""
DATA WORLD MAGAZINE
Professional, interactive magazine with smooth page-flip animations.
Clean architecture with high code quality and maintainable structure.

Articles are plain text files in the  articles/  folder next to this file.
See section 6 ("ARTICLE LOADER") for the file format.
"""

import streamlit as st
from pydantic import BaseModel
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple
from collections import deque
from functools import lru_cache, partial
import base64
import html as html_lib
import io
import json
import math
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

# ═══════════════════════════════════════════════════════════════════════════
# 1. PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Data World Magazine",
    page_icon='📖',
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 0 !important; padding-bottom: 0 !important; }
  /* stretch the magazine iframe to the full browser window */
  iframe { height: 100vh !important; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# 2. DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════

class Person(BaseModel):
    """Person featured in magazine"""
    name: str
    title: str
    linkedin_url: Optional[str] = None   # makes the person's box clickable (opens in a new tab)
    photo_url: Optional[str] = None   # path (relative to this file), http(s) URL, or data URI
    accent_color: str = "#c94f28"


class TableOfContentsEntry(BaseModel):
    """
    Table of contents entry (page numbers are calculated automatically).
    The page comes from the article or appendix whose number matches `number`.
    Set page_of="extras" to point at the first video / app page instead.
    """
    number: str
    title: str
    subtitle: str
    page_of: str = ""


class ArticleImage(BaseModel):
    """
    A picture placed inside an article. Pictures keep their own proportions (never cropped).
    layout: "banner"   = spans both columns, centred (best for wide / landscape shots)
            "column"   = one column wide, sits in the text flow
            "inset"    = small, floats right with the text wrapping around it
            "polaroid" = white-framed print with a slight tilt, caption inside the frame
            "feature"  = big, centred, spans both columns (for diagrams / hero pictures)
    after:  the picture goes after this paragraph of the article (1 = after the first paragraph)
    after_text: optional. If set, the picture goes after the first paragraph that contains this
            text (not case-sensitive), which stays put even if paragraphs get added or removed.
            `after` is only used when this is blank or the text isn't found.
    """
    file: str                   # path relative to this file, e.g. "images/maggie_wids.jpg"
    caption: str = ""
    layout: str = "column"
    after: int = 1
    after_text: str = ""


class ImageBlock(BaseModel):
    """An ArticleImage after the file has been read and measured"""
    src: str = ""               # base64 data URI ("" while the file is missing)
    label: str = ""
    caption: str = ""
    layout: str = "column"
    aspect: float = 4 / 3       # width / height
    width: float = 0            # on-page size in px
    height: float = 0


class Article(BaseModel):
    """
    One article in the issue. The text comes from articles/<file>.txt
    Anything in the text file's header (Title / Byline / Lead / Quote) wins;
    title, byline, lead and pull_quote here are only fallbacks.
    """
    number: str
    file: str                  
    title: str = ""
    byline: str = ""
    lead: str = ""
    pull_quote: str = ""
    label: str = "Article"      # small tag above the title: "Article 01", "Appendix A", ...
    images: List[ArticleImage] = []     # pictures placed inside the article (see ArticleImage)


class AppFeature(BaseModel):
    """
    A spread that shows a deployed Streamlit app inside the magazine.
    layout="split": left page = intro text, right page = the live app
    layout="full":  the app fills both pages
    """
    title: str
    url: str                    # the deployed app's URL, e.g. https://your-app-name.streamlit.app
    blurb: str = ""             # intro text for the left page ("split" layout); blank line = new paragraph
    kicker: str = "Try It"      # small label above the title
    layout: str = "split"       # "split" or "full"
    after: str = ""             # article number to place it after ("02"); "" = before the first article


class VideoFeature(BaseModel):
    """
    A single page that shows a YouTube video (click the thumbnail to play).
    The page is placed right after the article whose number is in `after`.
    """
    title: str
    url: str = ""                # any YouTube link: watch?v=..., youtu.be/..., /shorts/..., /embed/...
    caption: str = ""            # text under the video; blank line = new paragraph
    kicker: str = "Watch"        # small label above the title
    after: str = ""              # article number to place it after ("01"); "" = before the first article


class ImagePages(BaseModel):
    """
    One page (1 file) or a two-page spread (2 files: left page, right page) made of pictures.
    mode: "fit"    = the whole picture is shown on the page, never cropped
          "cover"  = the picture fills the whole page (a sliver of the edges may be trimmed);
                     use it for full designed pages that are almost exactly page-shaped
          "scroll" = the picture fills the page width and the reader scrolls down (tall infographics)
    after: article number to place it after; it goes after any video / app with the same `after`.
    toc_key: optional. A table-of-contents entry whose page_of equals this value shows the page
            where this feature starts (e.g. toc_key="flattening" + TableOfContentsEntry(page_of="flattening")).
    label: optional small label printed centred above the picture on every page of the feature
            (e.g. label="Advertisement").
    """
    title: str
    files: List[str]            # paths relative to this file, e.g. "article_pics/franco_ad.jpg"
    mode: str = "fit"
    after: str = ""
    toc_key: str = ""
    label: str = ""


class LoadedArticle(BaseModel):
    """Article after the text file has been read and parsed"""
    label: str
    number: str
    title: str
    byline: str
    lead: str
    pull_quote: str
    blocks: List[tuple]   # ("p", text) paragraphs, ("sub", text) subheadings, ("img", ImageBlock) pictures


class Issue(BaseModel):
    """Complete magazine issue"""
    number: str
    year: int
    theme: str
    editor_letter: str
    toc: List[TableOfContentsEntry]
    people: List[Person]
    articles: List[Article]
    appendix: List[Article] = []     # shown after everything else, before the Notes pages
    apps: List[AppFeature] = []
    videos: List[VideoFeature] = []
    pages: List[ImagePages] = []     # picture pages / spreads (infographics, ads)


# ═══════════════════════════════════════════════════════════════════════════
# 3. IMAGE LOADERS
# ═══════════════════════════════════════════════════════════════════════════

MIME_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
}


def load_cover_image() -> str:
    """Load cover.png from same directory and return as base64 data URI"""
    cover_path = Path(__file__).parent / "fall_cover.png"
    if cover_path.exists():
        data = cover_path.read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    return ""


@lru_cache(maxsize=None)
def load_local_image(path: Optional[str]) -> Optional[str]:
    """
    Resolve a photo reference to something an <img> can display.
    - http(s) URLs and data URIs pass through unchanged
    - local paths (e.g. 'headshots/maggiew.jpg') are read from disk next to this
      file and embedded as base64 (the magazine renders inside an iframe, so
      plain relative paths wouldn't load)
    - returns None if the file doesn't exist yet (a placeholder is shown instead)
    """
    if not path:
        return None
    if path.startswith(("http://", "https://", "data:")):
        return path
    file_path = Path(__file__).parent / path
    if not file_path.exists():
        return None
    mime = MIME_TYPES.get(file_path.suffix.lower(), "image/jpeg")
    b64 = base64.b64encode(file_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


MAX_FIGURE_PX = 900     # article pictures are shrunk to this width so the page stays light


@lru_cache(maxsize=None)
def load_figure_image(path: str, max_px: int = MAX_FIGURE_PX) -> Optional[Tuple[str, float]]:
    """
    Read an article picture. Returns (base64 data URI, width/height) or None if the file
    isn't there yet. Phone-photo rotation (EXIF) is applied so the measured shape is the shape you see.
    max_px is the widest the picture may be (wider ones are shrunk); picture pages pass a larger value.
    """
    file_path = Path(__file__).parent / path
    if not file_path.exists():
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(file_path) as im:
            im = ImageOps.exif_transpose(im)
            if im.width > max_px:
                im = im.resize((max_px, round(im.height * max_px / im.width)), Image.LANCZOS)
            has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            buf = io.BytesIO()
            if has_alpha:
                im.save(buf, "PNG", optimize=True)
                mime = "image/png"
            else:
                im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
                mime = "image/jpeg"
            aspect = im.width / im.height
        return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}", aspect
    except Exception:
        mime = MIME_TYPES.get(file_path.suffix.lower(), "image/jpeg")
        return f"data:{mime};base64,{base64.b64encode(file_path.read_bytes()).decode('utf-8')}", 4 / 3



# ═══════════════════════════════════════════════════════════════════════════
# 5. CONTENT DATA (Edit here to customize magazine)
# ═══════════════════════════════════════════════════════════════════════════

# How many blank spreads (2 pages each) to add at the end of the magazine.
NUM_BLANK_SPREADS = 0

# Optional: raw HTML to drop onto specific blank pages.
# Key = blank page number counting from 1 (1 = first blank page, 2 = second, ...)
# Example: {1: "<h2>Notes</h2><p>My text here</p>"}
BLANK_PAGE_CONTENT = {}

# True  = every article starts on a left-hand page (a blank page is added after
#         an article that ends on a left-hand page).
# False = the next article starts right after the previous one, even on a
#         right-hand page, so no blank filler pages appear between articles.
# (A "full" app needs both pages of a spread, so it can still force one blank page.
# A "split" app never does: if it would land on a right-hand page, its intro goes
# there and the live app appears on the next left-hand page.)
ARTICLES_START_ON_LEFT = False

# Set to True to print a page-by-page map under the magazine (handy for checking
# which page is which and where a blank page comes from). Turn off before sharing.
SHOW_PAGE_MAP = False

# Photo shown beside the signature on the Editor's Letter page.
# Path is relative to this file (or an http(s) URL). A placeholder shows until the file exists.
EDITOR_PHOTO = "headshots/evelyn.png"

# Two photo spots on the Editor's Letter page: [tall photo beside the headline,
# wider photo beside the letter text]. Paths are relative to this file (or http(s) URLs).
# A placeholder shows until the file exists. Photos are cropped to fill the spot.
EDITOR_IMAGES = ["dreamteam.jpeg", "friends.png"]

# Tall "film strip" picture for the Editor's Letter page (friends.png). It takes the spot beside the
# letter text, so the second EDITOR_IMAGES photo is skipped while this is on, and it is NEVER cropped:
# it keeps its own shape. Path is relative to this file (or an http(s) URL).
# EDITOR_STRIP_W     = how wide it is on the page (its height follows from its shape)
# EDITOR_STRIP_MAX_H = tallest it may get
# Set EDITOR_STRIP = "" to go back to the cropped second photo in EDITOR_IMAGES.
EDITOR_STRIP = "friends.png"
EDITOR_STRIP_W = 124
EDITOR_STRIP_MAX_H = 385

# "Meet the Editor" page: the full-page picture on page 6 (right of People in Data) + a LinkedIn button under it.
# Path is relative to this file (or an http(s) URL). A placeholder shows until the file exists.
# The button stays hidden until EDITOR_LINKEDIN_URL is a real link; set it to "" to leave the button off.
# To swap the picture later, replace the file (or change the name here). Restart the app if the old one still shows.
EDITOR_PAGE_IMAGE = "meet_editor.png"
EDITOR_LINKEDIN_URL = "https://www.linkedin.com/in/evelyntcates"
EDITOR_LINKEDIN_LABEL = "Connect with me on LinkedIn ↗"

# Back cover: the last spread. The book "closes" (the back cover slides to the middle, like the front cover).
# BACK_COVER_IMAGE = your back cover picture, next to this file (like fall_cover.png). Best shape is the same as
#   the front cover (about 520 x 720). A labelled placeholder shows until the file exists.
#   Set it to "" to use the designed back cover instead (the words below).
# BACK_COVER_THANKS / BACK_COVER_TAGLINE = the words on the designed back cover (<em>..</em> = accent colour italic).
# Set SHOW_BACK_COVER = False to leave the back cover off.
SHOW_BACK_COVER = True
BACK_COVER_IMAGE = "back_cover.png"
BACK_COVER_THANKS = "Thank you for <em>reading.</em>"
BACK_COVER_TAGLINE = "Data has always been about people."

# A dark "next issue" page, on its own spread just before the back cover.
# NEXT_ISSUE      = the big words (<em>..</em> = accent colour italic). Set it to "" to leave this page out.
# NEXT_ISSUE_FONT = a Google Fonts family name for the words on that page. "Fraunces" is the font used for
#                   the magazine's headings; swap in another family name if you want a different look.
NEXT_ISSUE = "Winter <em>2027</em>"
NEXT_ISSUE_FONT = "Fraunces"

# Page number of the first article page.
# Layout: 1-2 cover, 3-4 letter & TOC, 5-6 people & meet the editor, 7+ articles.
ARTICLE_START_PAGE = 7

# ── SIZE CONTROLS ──────────────────────────────────────────────────────────
# PAGE_W / PAGE_H: size of ONE page in layout pixels. Bigger pages hold more
#   text, so articles use fewer pages. The whole book is then scaled
#   automatically to fit your browser window, so a bigger page doesn't mean it
#   spills off the screen -- it just means everything is drawn a bit smaller.
#   Keep PAGE_H / PAGE_W close to 1.38 so cover.png isn't letterboxed.
# BODY_FONT_PX: article text size. Raise it if text looks small after scaling.
# IFRAME_HEIGHT: fallback height; the CSS below stretches it to the full window.
PAGE_W = 520
PAGE_H = 720
BODY_FONT_PX = 13
IFRAME_HEIGHT = 900

# ── ARTICLE COLUMNS ────────────────────────────────────────────────────────
# ARTICLE_COLUMNS: 2 = magazine-style columns (titles, bylines and pull quotes
#   stay full width). 1 = the old single-column pages.
# COLUMN_GAP_PX: space between columns.
# COLUMN_FONT_PX: article text size when using columns (narrow columns read
#   better with slightly smaller text). With 1 column, BODY_FONT_PX is used.
ARTICLE_COLUMNS = 2
COLUMN_GAP_PX = 22
COLUMN_FONT_PX = 11.5
# ARTICLE_JUSTIFY: True = straight right edge like print (words are hyphenated to
#   keep spacing even). False = ragged right, which avoids wide word gaps.
ARTICLE_JUSTIFY = True

# Folder (next to this file) that holds the article text files.
ARTICLES_DIR = Path(__file__).parent / "articles"

MAGAZINE = Issue(
    number="Fall Issue",
    year=2026,
    theme="People in Data",

    editor_letter="""Welcome to the first issue of <strong>Data World Magazine!!</strong> 
    <br>I’ve had the magazine idea for over two years now and last year, I figured out how to execute it. I started working on it and life got busy so I set it aside until I got laid off this year. </br>
    <br>This is my second time having gone through it and once again I’m reminded the importance of community and how that’s been keeping me sane!</br>
    <br>I decided to dust off the code for this magazine, reach out to wonderful data people I’m fortunate enough to learn from and create something that can help someone learn or feel comfort in community.</br>
    <br>I hope you enjoy the first fall issue that was created with lots of love ♥️ & 🧠 mental energy!.</br>""",

    toc=[
        TableOfContentsEntry(
            number="01",
            title="Your Future Career Might Not Exist Yet",
            subtitle="By: Maggie Wolff, Data Scientist, Former Marketer, Lifelong Learner",
        ),
        TableOfContentsEntry(
            number="02",
            title="Why Data Leadership Fails and How We Can Fix It",
            subtitle="What the data actually says about what we watch",
        ),
        TableOfContentsEntry(
            number="03",
            title="From Requirements to Dashboards ",
            subtitle="How Business Analysts Bridge the Gap Between What the Business Wants and What Data Can Show",
        ),
        TableOfContentsEntry(
            number="05",
            title="The Great Flattening: What AI Is Changing About the Shape of Work",
            subtitle="By: Laurel Babarogich, I/O Psychologist",
            page_of="flattening",
        ),
        TableOfContentsEntry(
            number="04",
            title="There's videos to check out, Career quizzes and More!!",
            subtitle="Make sure to check them out",
            page_of="extras",
        ),
        TableOfContentsEntry(
            number="A",
            title="Appendix: Your Future Career Might Not Exist Yet",
            subtitle="The rest of Maggie Wolff's article",
        ),
    ],

    # The four boxes on the "People in Data" page, in reading order
    # (left → right, top → bottom). Drop each headshot into the headshots/
    # folder next to this file and make sure photo_url matches the file name.
    people=[
        Person(
            name="Maggie Wolff",
            title="Data Scientist, Former Marketer, Lifelong Learner",
            linkedin_url="https://www.linkedin.com/in/magwolff/",
            photo_url="headshots/maggiew.jpg",
            accent_color="#c94f28",
        ),
        Person(
            name="Tristan Burns",
            title="Strategy & Data Leadership Coach",
            linkedin_url="https://www.linkedin.com/in/tristanjburns",
            photo_url="headshots/trisb.jpeg",
            accent_color="#c94f28",
        ),
        Person(
            name="Megan Tuano",
            title="Business Analyst -> Project Manager",
            linkedin_url="https://www.linkedin.com/in/megantuano/",  
            photo_url="headshots/megant.png",
            accent_color="#2a6e4e",
        ),
        Person(
            name="Jess Ramos",
            title="Founder-Big Data Energy",
            linkedin_url="https://www.linkedin.com/in/jessramosmsba/",   
            photo_url="headshots/jessr.webp",
            accent_color="#c49a2a",
        ),
    ],

    # One entry per article, in magazine order. `file` is the first name that
    # matches the text file in articles/ (case doesn't matter, extension is
    # optional): "maggie" finds articles/maggie.txt, articles/Maggie.md, etc.
    # >>> Change the `file` values below to match your actual file names. <<<
    # title / byline are only used if the text file doesn't have its own header.
    #
    # `images` places pictures inside an article (files live in the images/ folder).
    #   layout: "banner" | "feature" | "column" | "inset" | "polaroid"   (see ArticleImage in section 2)
    #   after:  paragraph number the picture follows (2 = after the 2nd paragraph)
    #   after_text: (optional) place it after the paragraph containing this text instead
    #   caption: optional text under the picture (inside the frame for "polaroid")
    articles=[
        Article(
            number="01",
            file="maggie",
            title="Your Future Career Might Not Exist Yet",
            byline="By: Maggie Wolff",
            images=[
                ArticleImage(file="article_pics/maggie_masters_graduate.jpg", layout="inset",    after=2, caption=""),
                ArticleImage(file="article_pics/maggie_measurecamp.jpg",      layout="banner",   after=5, caption=""),
                ArticleImage(file="article_pics/maggie_wids.jpg",             layout="polaroid", after=12, caption=""),
            ],
        ),
        Article(
            number="02",
            file="tristan",
            title="Why Data Leadership Fails and How We Can Fix It",
            byline="By: Tristan Burns",
            images=[
                ArticleImage(file="article_pics/tris_speaking.jpeg",  layout="banner",   after=2, caption=""),
                ArticleImage(file="article_pics/tris_books.jpeg",     layout="polaroid", after=2, caption="My To Be Read Stack"),
                ArticleImage(file="article_pics/tris_strategy.jpeg",  layout="feature",  after=5, after_text="I also write the newsletter", caption=""),
            ],
        ),
        Article(
            number="03",
            file="megan",
            title="From Requirements to Dashboards: How Business Analysts Bridge the Gap",
            byline="By: Megan Tuano",
            images=[
                ArticleImage(file="article_pics/megan_working.jpg",  layout="feature",   after=1, caption=""),
                ArticleImage(file="article_pics/megan_speaking.png", layout="banner", after=4, caption=""),
                ArticleImage(file="article_pics/meg_fall_work.png",  layout="inset",  after=1, caption="")
            ],
        ),
        Article(
            number="05",
            file="laurel",
            title="The Great Flattening: What AI Is Changing About the Shape of Work",
            byline="By: Laurel Babarogich, I/O Psychologist",
        ),
    ],

    # Extra articles that come after the main issue (and after any apps/videos).
    # `file` works like the articles above: "maggie_appendix" finds articles/maggie_appendix.txt
    appendix=[
        Article(
            number="A",
            label="Appendix",
            file="maggie_appendix",
            title="Your Future Career Might Not Exist Yet (continued)",
            byline="By: Maggie Wolff",
        ),
    ],

    # Streamlit apps shown inside the magazine (each one = one 2-page spread).
    # `url` must be a DEPLOYED app (e.g. on Streamlit Community Cloud).
    # `after="01"` puts it right after article 01 (and after any video also set to "01").
    # While the url still contains "your-app-name", the page shows a reminder instead of an app.
    apps=[
        AppFeature(
            title="What Data Career Should You Do?!",
            kicker="Take a Quiz!",
            blurb="As a millennial who grew up on random online quizzes, I had the idea to create one to help me better understand what my next data job should be.\n\n I hope you find this fun and insightful as I did!",
            url="https://dataquizapp.streamlit.app/",
            layout="split",
            after="01",
        ),
        AppFeature(
            title="Interview Prep Framework",
            kicker="Try It",
            blurb="I created this interview prep to help with the overwhelming feeling of preparing for interviews\n\n",
            url="https://interviewprepframework.streamlit.app/",                
            layout="split",
            after="03",                   # after the last article, right before the appendix
        ),
    ],

    # YouTube videos shown on their own page (click the thumbnail to play).
    # `after="01"` puts the video on the page right after article 01.
    # Paste any YouTube link into `url`; until then the page shows a reminder.
    videos=[
        VideoFeature(
            title="The Data Job Market Is About To Change (2026)",
            url="https://www.youtube.com/watch?v=Nc-YdL7YWGo",
            caption="Watch this video if you're curious about the 2026 data job market",
            after="01",
        ),
        VideoFeature(
            title="This or That AI Edition",
            url="https://www.youtube.com/watch?v=QCHrS7n4lTw",
            caption="There are SO many AI tools out now, which ones are your go to?!",
            after="03",
        ),
    ],

    # Picture pages: an infographic spread, an ad page, etc. (files live in article_pics/).
    # 1 file = one page, 2 files = a two-page spread (left file, right file).
    # mode="scroll": the picture fills the page width and the reader scrolls (tall infographics)
    # mode="fit":    the whole picture is shown on the page, never cropped
    # `after="03"` puts a feature right after article 03 and after the video / Interview Prep app set to "03".
    # `toc_key` ties a feature to a table-of-contents entry whose page_of has the same value (see `toc` above).
    # A two-page spread always starts on a left-hand page. If the next page is a right-hand page and the
    # same `after` also holds a one-page picture, that picture is placed there first so no blank is needed.
    pages=[
        ImagePages(
            title="The Great Flattening",
            files=["article_pics/flattening_left.jpg", "article_pics/flattening_right.jpg"],
            mode="scroll",
            after="03",
            toc_key="flattening",
        ),
        ImagePages(
            title="Franco Career Consulting",
            files=["article_pics/franco_ad.jpg"],
            mode="fit",
            after="02",             # after Tristan's article, before Megan's
            label="Advertisement",
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# 6. ARTICLE LOADER (text file -> parsed article -> pages)
# ═══════════════════════════════════════════════════════════════════════════
#

# ----------
# The text is flowed across as many pages as it needs. Page sizes can't be
# measured in Python, so line wrapping is ESTIMATED from PAGE_W, PAGE_H and
# BODY_FONT_PX (section 5). If text gets cut off at the bottom of a page, raise
# PAGE_BODY_MARGIN_PX (or CHAR_WIDTH_EM; COLUMN_CHAR_WIDTH_EM when using columns). If pages end with too much empty
# space, lower them.
# Whether articles must start on a left-hand page is controlled by
# ARTICLES_START_ON_LEFT (section 5); the page layout itself is in section 10.

PAGE_PAD_X = 26                                   # left/right padding inside a page
INNER_W = PAGE_W - 2 * PAGE_PAD_X                 # usable text width
CHAR_WIDTH_EM = 0.516                             # average body-text character width, in em
ART_FONT_PX = COLUMN_FONT_PX if ARTICLE_COLUMNS > 1 else BODY_FONT_PX
ART_LINE_HEIGHT = 1.65 if ARTICLE_COLUMNS > 1 else 1.75
COL_W = (INNER_W - (ARTICLE_COLUMNS - 1) * COLUMN_GAP_PX) / ARTICLE_COLUMNS   # one column's width
COLUMN_CHAR_WIDTH_EM = 0.48                       # same idea, tuned for narrow justified/hyphenated columns
CHARS_PER_LINE = int(COL_W / (ART_FONT_PX * (COLUMN_CHAR_WIDTH_EM if ARTICLE_COLUMNS > 1 else CHAR_WIDTH_EM)))
LINE_PX = ART_FONT_PX * ART_LINE_HEIGHT              # body line-height
PARA_GAP_PX = 10                                  # space under each paragraph
SUBHEAD_FONT_PX = 14                              # subheading text size
SUBHEAD_LINE_PX = SUBHEAD_FONT_PX * 1.2           # subheading line-height
SUBHEAD_MARGIN_PX = 20                            # space above (14) + below (6) a subheading
COLUMN_SLACK_PX = LINE_PX * 0.5 if ARTICLE_COLUMNS > 1 else 0   # per-column safety margin (balancing isn't exact)
PAGE_BODY_MARGIN_PX = 80                          # top padding + footer + safety buffer
PAGE_BODY_PX = PAGE_H - PAGE_BODY_MARGIN_PX       # usable text height on a page
ARTICLE_TAG_PX = 23                               # "ARTICLE 01" label at the top of each article page

# ── PICTURES INSIDE ARTICLES ───────────────────────────────────────────────
# INSET_W: width of a floated "inset" picture.  FIGURE_MAX_H: tallest each layout may get (px).
# FIGURE_SLACK: extra room reserved around in-column pictures. Columns balance, so an
#   unsplittable picture can leave a small gap; raise it if text gets clipped on picture pages,
#   lower it if those pages end with too much empty space.
INSET_W = int(COL_W * 0.62)
FIGURE_MAX_H = {"banner": 240, "feature": 340, "column": 300, "inset": 190, "polaroid": 250}
POLAROID_PAD = 18               # frame thickness left + right (padding + border)
FIGURE_SLACK = 0.35
CAPTION_FONT_PX = 9.5


def chars_per_line(font_px: float, width_em: float, width: int = INNER_W) -> int:
    """How many characters of a given font size fit on one line of `width` px"""
    return max(10, int(width / (font_px * width_em)))


HEADER_KEYS = {
    "title": "title",
    "byline": "byline", "by": "byline",
    "lead": "lead", "subtitle": "lead",
    "quote": "pull_quote", "pull quote": "pull_quote", "pullquote": "pull_quote",
}
HEADER_RE = re.compile(r"^\s*([A-Za-z ]+?)\s*:\s*(.*)$")


def find_article_file(key: str) -> Optional[Path]:
    """Find articles/<key>.* (case-insensitive). A folder named <key> also works."""
    if not ARTICLES_DIR.is_dir():
        return None
    wanted = key.strip().lower()
    for entry in sorted(ARTICLES_DIR.iterdir()):
        if entry.name.lower() != wanted and entry.stem.lower() != wanted:
            continue
        if entry.is_file():
            return entry
        if entry.is_dir():
            inside = sorted(p for p in entry.iterdir()
                            if p.is_file() and p.suffix.lower() in (".txt", ".md"))
            if inside:
                return inside[0]
    return None


def parse_article_text(raw: str) -> Tuple[dict, List[Tuple[str, str]]]:
    """Split raw text into (header fields, body blocks)"""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").strip()

    # Header = first block, only if every line in it is a recognised "Key: value" (or "# Title")
    fields, body = {}, raw
    head, _, rest = raw.partition("\n\n")
    parsed = {}
    is_header = True
    for line in head.split("\n"):
        match = HEADER_RE.match(line)
        if match and match.group(1).strip().lower() in HEADER_KEYS:
            parsed[HEADER_KEYS[match.group(1).strip().lower()]] = match.group(2).strip()
        elif line.startswith("# ") and "title" not in parsed:
            parsed["title"] = line[2:].strip()
        else:
            is_header = False
            break
    if is_header and parsed:
        fields, body = parsed, rest

    blocks: List[Tuple[str, str]] = []
    for chunk in re.split(r"\n\s*\n", body):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("## "):
            first, _, remainder = chunk.partition("\n")
            blocks.append(("sub", first[3:].strip()))
            chunk = remainder.strip()
            if not chunk:
                continue
        blocks.append(("p", re.sub(r"\s*\n\s*", " ", chunk)))
    return fields, blocks


def figure_size(layout: str, aspect: float) -> Tuple[float, float]:
    """On-page (width, height) of a picture's image area, keeping the picture's own shape"""
    max_w = {"banner": INNER_W, "feature": INNER_W * 0.86, "column": COL_W, "inset": INSET_W,
             "polaroid": COL_W * 0.92 - POLAROID_PAD}[layout]
    w = min(max_w, FIGURE_MAX_H[layout] * aspect)
    return w, w / aspect


def make_image_block(img: ArticleImage) -> ImageBlock:
    """Read + measure one picture and work out its on-page size"""
    layout = img.layout if img.layout in FIGURE_MAX_H else "column"
    loaded = load_figure_image(img.file)
    src, aspect = loaded if loaded else ("", 4 / 3)       # placeholder shows 4:3 until the file exists
    width, height = figure_size(layout, aspect)
    return ImageBlock(src=src, label=img.file, caption=img.caption, layout=layout,
                      aspect=aspect, width=width, height=height)


def image_cost(fig: ImageBlock) -> float:
    """Column-pixels a picture uses up on a page (a banner spans every column, so it costs every column)"""
    frame = POLAROID_PAD if fig.layout == "polaroid" else 0
    caption = (_lines(fig.caption, chars_per_line(CAPTION_FONT_PX, 0.5, int(fig.width + frame))) * 13.5 + 6
               if fig.caption else 0)
    if fig.layout in ("banner", "feature"):
        return (fig.height + caption + 20) * ARTICLE_COLUMNS + LINE_PX * 1.5
    extra = 48 if fig.layout == "polaroid" else 14
    return (fig.height + caption + extra) * (1 + FIGURE_SLACK)


def insert_images(blocks: list, images: List[ArticleImage]) -> list:
    """Drop each picture in after its paragraph number (anything past the end goes at the end)"""
    by_para: Dict[int, list] = {}
    for img in images:
        para = img.after
        if img.after_text:
            needle, count = img.after_text.lower(), 0
            for kind, text in blocks:
                if kind == "p":
                    count += 1
                    if needle in text.lower():
                        para = count
                        break
        by_para.setdefault(max(1, para), []).append(make_image_block(img))
    out, count = [], 0
    for block in blocks:
        out.append(block)
        if block[0] == "p":
            count += 1
            out.extend(("img", fig) for fig in by_para.pop(count, []))
    for key in sorted(by_para):
        out.extend(("img", fig) for fig in by_para[key])
    return out


def load_article(article: Article) -> LoadedArticle:
    """Read the article's text file and merge it with the fallbacks in MAGAZINE"""
    path = find_article_file(article.file)
    fields, blocks = {}, []
    if path:
        fields, blocks = parse_article_text(path.read_text(encoding="utf-8-sig"))
    if not blocks:
        blocks = [("p", f"[No article text found. Add a file named {article.file}.txt to the articles folder.]")]
    blocks = insert_images(blocks, article.images)
    return LoadedArticle(
        label=article.label,
        number=article.number,
        title=fields.get("title") or article.title,
        byline=fields.get("byline") or article.byline,
        lead=fields.get("lead") or article.lead,
        pull_quote=fields.get("pull_quote") or article.pull_quote,
        blocks=blocks,
    )


def inline_format(text: str) -> str:
    """Escape HTML, then turn **bold** and *italic* into tags"""
    out = html_lib.escape(text, quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", out)
    return out


def _lines(text: str, chars_per_line: int) -> int:
    return max(1, math.ceil(len(text) / chars_per_line))


def subhead_px(text: str) -> float:
    """Height of a subheading (it can wrap to 2+ lines in a narrow column)"""
    lines = _lines(text, chars_per_line(SUBHEAD_FONT_PX, 0.57, int(COL_W)))
    return lines * SUBHEAD_LINE_PX + SUBHEAD_MARGIN_PX


def paginate(blocks, first_capacity: float, cont_capacity: float, quote_px: float) -> List[dict]:
    """
    Flow blocks across pages. Returns a list of {"blocks": [...], "quote": bool}.
    Capacities are in "column pixels": a page with 2 columns passes 2 x its column height,
    because the text fills one column after the other.
    - Paragraphs that don't fit are split at a word boundary (no 1-line widows/orphans)
    - Subheadings never sit alone at the bottom of a page
    - Pictures are never split; one that doesn't fit waits and opens the next page
      (the text keeps filling the current page in the meantime)
    - If there's a pull quote, space is reserved for it at the bottom of page 2
    The result is NOT padded to an even length; section 10 decides where blank
    pages are needed.
    """
    pages = [{"blocks": [], "quote": False}]
    state = {"rem": first_capacity}
    waiting: list = []                     # pictures that didn't fit; they open the next page

    def new_page():
        pages.append({"blocks": [], "quote": False})
        capacity = cont_capacity
        if len(pages) == 2 and quote_px:
            capacity -= quote_px
            pages[-1]["quote"] = True
        state["rem"] = capacity
        while waiting:
            fig = waiting.pop(0)
            pages[-1]["blocks"].append(("img", fig))
            state["rem"] -= image_cost(fig)

    queue = deque(blocks)
    while queue:
        kind, text = queue.popleft()
        page = pages[-1]
        empty = not page["blocks"]

        if kind == "img":
            cost = image_cost(text)
            if cost <= state["rem"] or empty:
                page["blocks"].append((kind, text))
                state["rem"] -= cost
            else:
                waiting.append(text)
            continue

        if kind == "sub":
            sub_px = subhead_px(text)
            if not empty and state["rem"] < sub_px + 3 * LINE_PX:
                new_page()
                page = pages[-1]
            page["blocks"].append((kind, text))
            state["rem"] -= sub_px
            continue

        lines = _lines(text, CHARS_PER_LINE)
        need = lines * LINE_PX + PARA_GAP_PX
        if need <= state["rem"]:
            page["blocks"].append((kind, text))
            state["rem"] -= need
            continue

        fit = int(state["rem"] // LINE_PX)
        rest_lines = lines - fit
        if fit >= 2 and (rest_lines >= 2 or empty):
            cut = fit * CHARS_PER_LINE
            space = text.rfind(" ", 0, cut + 1)
            if space > CHARS_PER_LINE:
                head, tail = text[:space], text[space + 1:]
            else:
                head, tail = text[:cut], text[cut:]
            page["blocks"].append(("p", head.strip()))
            queue.appendleft(("p", tail.strip()))
            new_page()
        elif empty:
            page["blocks"].append((kind, text))   # nothing better to do; page clips it
            state["rem"] = 0
        else:
            new_page()
            queue.appendleft((kind, text))

    if waiting:
        new_page()                                 # a leftover picture gets its own page
    if quote_px and len(pages) < 2:
        new_page()                                 # quote needs its own page 2
    return pages


def layout_article(art: LoadedArticle) -> List[dict]:
    """Work out how much room the title block takes, then paginate the body"""
    long_title = len(art.title) > 70
    title_font, title_lh = (17, 20.4) if long_title else (26, 28)
    title_px = _lines(art.title, chars_per_line(title_font, 0.57)) * title_lh
    header_px = ARTICLE_TAG_PX + title_px + 10
    if art.byline:
        header_px += _lines(art.byline, chars_per_line(10, 0.736)) * 14 + 28
    if art.lead:
        header_px += _lines(art.lead, chars_per_line(13, 0.515)) * 20.2 + 12
    quote_px = 0
    if art.pull_quote:
        quote_px = _lines(art.pull_quote, chars_per_line(16, 0.58, INNER_W - 15)) * 21 + 26
    # Column height left for text on each kind of page (the quote sits below the columns)
    first_h = PAGE_BODY_PX - header_px - COLUMN_SLACK_PX
    cont_h = PAGE_BODY_PX - ARTICLE_TAG_PX - COLUMN_SLACK_PX
    return paginate(art.blocks, first_h * ARTICLE_COLUMNS, cont_h * ARTICLE_COLUMNS,
                    quote_px * ARTICLE_COLUMNS)


# ═══════════════════════════════════════════════════════════════════════════
# 7. HTML BUILDERS (Convert data to HTML components)
# ═══════════════════════════════════════════════════════════════════════════

def normalize_url(url: str) -> str:
    """Add https:// when a URL was written without a scheme (e.g. www.linkedin.com/in/name)"""
    url = url.strip()
    return url if url.startswith(("http://", "https://")) else "https://" + url


def app_url_is_placeholder(url: str) -> bool:
    return (not url.strip()) or "your-app-name" in url.lower()


def streamlit_embed_url(url: str) -> str:
    """Streamlit apps embed cleanly (no header/footer) when the URL has ?embed=true"""
    parsed = urlparse(normalize_url(url))
    query = dict(parse_qsl(parsed.query))
    query.setdefault("embed", "true")
    return urlunparse(parsed._replace(query=urlencode(query)))


YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_id(url: str) -> Optional[str]:
    """Pull the 11-character video id out of any common YouTube link (or a bare id)"""
    url = url.strip()
    if not url:
        return None
    if YOUTUBE_ID_RE.match(url):
        return url
    parsed = urlparse(normalize_url(url))
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    candidate = None
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if parsed.path == "/watch":
            candidate = dict(parse_qsl(parsed.query)).get("v")
        else:
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v"):
                candidate = parts[1]
    return candidate if candidate and YOUTUBE_ID_RE.match(candidate) else None


def photo_element(person: Person) -> str:
    """Headshot <img> if the file exists, otherwise a placeholder showing where to put it"""
    src = load_local_image(person.photo_url)
    if src:
        return f'<img src="{src}" alt="{person.name}">'
    label = person.photo_url or "add headshot"
    return f'<div class="ic">👤</div><div class="lb">{label}</div>'


def page_foot(issue: Issue, page_num: int) -> str:
    """Shared footer with running title and page number"""
    return f"""
      <div class="pg-foot">
        <span>Data World Magazine</span>
        <span>{issue.number} · {issue.year}</span>
        <strong>{page_num:02d}</strong>
      </div>"""


def build_cover_page(cover_src: str) -> str:
    """Build full-bleed cover image page (left side only)"""
    if cover_src:
        img_html = f'<img src="{cover_src}" style="width:100%;height:100%;object-fit:contain;display:block;">'
    else:
        img_html = '<div style="width:100%;height:100%;background:var(--ink);display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.2);font-size:13px;">cover.png not found</div>'

    return f'<div class="pg pg-cover-photo">{img_html}</div>'


def build_cover_back() -> str:
    """Build blank dark right page that pairs with cover image"""
    return '<div class="pg pg-cover-back"></div>'


def build_next_issue_page(issue: Issue) -> str:
    """Inside of the back cover: a dark page announcing the next issue (plain dark page if NEXT_ISSUE is empty)"""
    if not NEXT_ISSUE:
        return build_cover_back()
    return f"""
    <div class="pg pg-next">
      <div class="nx-kicker">The next issue of</div>
      <div class="nx-name">Data World Magazine</div>
      <div class="nx-will">will be</div>
      <div class="nx-head">{NEXT_ISSUE}</div>
    </div>"""


def build_back_cover(issue: Issue) -> str:
    """
    Back cover (right-hand page of the last spread).
    - BACK_COVER_IMAGE set and the file exists -> the picture, like the front cover
    - BACK_COVER_IMAGE set but no file yet     -> a labelled placeholder showing where it goes
    - BACK_COVER_IMAGE = ""                    -> the designed back cover (BACK_COVER_THANKS / _TAGLINE)
    """
    if BACK_COVER_IMAGE:
        src = load_local_image(BACK_COVER_IMAGE)
        if src:
            return (f'<div class="pg pg-cover-photo"><img src="{src}" alt="" '
                    f'style="width:100%;height:100%;object-fit:contain;display:block;"></div>')
        return f"""
    <div class="pg pg-back">
      <div class="bk-tag">Back cover</div>
      <div class="bk-mid">
        <div class="bk-ph">
          <div class="ltr-ph-ic">🖼️</div>
          <div class="bk-ph-lb">{html_lib.escape(BACK_COVER_IMAGE)} not found</div>
          <div class="bk-ph-hint">Add your back cover image next to this file<br>(best shape: about {PAGE_W} × {PAGE_H})</div>
        </div>
        <button class="bk-btn" onclick="restart()">↺ Back to the front</button>
      </div>
      <div></div>
    </div>"""
    return f"""
    <div class="pg pg-back">
      <div class="bk-tag">{issue.number} · {issue.year}</div>
      <div class="bk-mid">
        <div class="bk-head">{BACK_COVER_THANKS}</div>
        <div class="bk-rule"></div>
        <div class="bk-tagline">{BACK_COVER_TAGLINE}</div>
        <button class="bk-btn" onclick="restart()">↺ Back to the front</button>
      </div>
      <div>
        <div class="bk-name">Data World Magazine</div>
        <div class="bk-sub">{issue.theme}</div>
      </div>
    </div>"""


def image_spot(path: str, css_class: str) -> str:
    """A framed image spot; shows a labelled placeholder until the file exists"""
    src = load_local_image(path)
    if src:
        inner = f'<img src="{src}" alt="">'
    else:
        inner = f'<div class="ltr-ph-ic">🖼️</div><div class="ltr-ph-lb">{html_lib.escape(path)}</div>'
    return f'<div class="ltr-img {css_class}">{inner}</div>'


def strip_spot(path: str) -> str:
    """Tall film-strip picture: never cropped, sized by EDITOR_STRIP_W (and capped in height)"""
    loaded = load_figure_image(path)
    aspect = loaded[1] if loaded else 1 / 3
    width = min(EDITOR_STRIP_W, EDITOR_STRIP_MAX_H * aspect)
    if loaded:
        return f'<div class="ltr-strip" style="width:{width:.0f}px"><img src="{loaded[0]}" alt=""></div>'
    return (f'<div class="ltr-strip ltr-strip-ph" style="width:{width:.0f}px;aspect-ratio:{aspect:.3f}">'
            f'<div class="ltr-ph-ic">🖼️</div><div class="ltr-ph-lb">{html_lib.escape(path)}</div></div>')


def build_editor_letter(issue: Issue) -> str:
    """
    Build editor's letter page HTML: tall photo beside the headline, the letter in a
    narrow column beside a wider photo, and the signature (with round photo) at the bottom.
    """
    photo_src = load_local_image(EDITOR_PHOTO)
    if photo_src:
        photo = f'<img src="{photo_src}" alt="Editor">'
    else:
        photo = f'<div class="ltr-ph-ic">👤</div><div class="ltr-ph-lb">{EDITOR_PHOTO}</div>'
    spots = (list(EDITOR_IMAGES) + ["", ""])[:2]
    if EDITOR_STRIP:
        side_class, side_photo = "ltr-side has-strip", strip_spot(EDITOR_STRIP)
    else:
        side_class, side_photo = "ltr-side", image_spot(spots[1], "ltr-img-b")
    return f"""
    <div class="pg pg-letter">
      <div class="ltr-top">
        {image_spot(spots[0], "ltr-img-a")}
        <div class="ltr-titleblock">
          <div class="ltr-tag">{issue.number} · Editor's Letter</div>
          <div class="ltr-head">Data has<br>always been<br>about <em>people.</em></div>
        </div>
      </div>
      <div class="ltr-mid">
        <div class="ltr-body">{issue.editor_letter}</div>
        <div class="{side_class}">
          {side_photo}
        </div>
      </div>
      <div class="ltr-sig">
        <div class="ltr-photo">{photo}</div>
        <div>
          <div class="ltr-name">Evelyn</div>
          <div class="ltr-role">Editor·Data World Magazine</div>
        </div>
      </div>
    </div>"""


def build_toc(issue: Issue, start_pages: Dict[str, int]) -> str:
    """Build table of contents page HTML (page numbers come from the page layout)"""
    toc_rows = "".join(f"""
      <div class="toc-row">
        <div class="toc-n">{entry.number}</div>
        <div>
          <div class="toc-t">{entry.title}</div>
          <span class="toc-s">{entry.subtitle}</span>
        </div>
        <div class="toc-p">{f"{start_pages[entry.page_of or entry.number]:02d}" if (entry.page_of or entry.number) in start_pages else ""}</div>
      </div>""" for entry in issue.toc)

    stats = f"""
      <div class="toc-stats">
        <div class="ts">
          <div class="ts-n">{len(issue.articles)}<span>+</span></div>
          <div class="ts-l">Stories</div>
        </div>
        <div class="ts">
          <div class="ts-n">{len(issue.people)}<span>+</span></div>
          <div class="ts-l">People</div>
        </div>
        <div class="ts">
          <div class="ts-n">1<span>st</span></div>
          <div class="ts-l">Issue Ever</div>
        </div>
      </div>"""

    return f"""
    <div class="pg pg-toc">
      <div class="pg-logo">Data World Magazine</div>
      <div class="toc-lbl">In This Issue</div>
      {toc_rows}
      {stats}
    </div>"""


def person_card(person: Person) -> str:
    """One headshot box. Clickable (opens LinkedIn in a new tab) when linkedin_url is set."""
    style = f"--card-accent:{person.accent_color}"
    link = normalize_url(person.linkedin_url) if person.linkedin_url else ""
    if link:
        open_tag = (f'<a class="pcard has-link" href="{html_lib.escape(link, quote=True)}" '
                    f'target="_blank" rel="noopener noreferrer" '
                    f'title="View {html_lib.escape(person.name)} on LinkedIn" style="{style}">')
        close_tag = "</a>"
        badge = '<span class="pcard-in">LinkedIn ↗</span>'
    else:
        open_tag, close_tag, badge = f'<div class="pcard" style="{style}">', "</div>", ""
    return f"""
      {open_tag}
        <div class="pcard-ph" style="background:linear-gradient(160deg,{person.accent_color}22,{person.accent_color}44)">
          {photo_element(person)}{badge}
        </div>
        <div class="pcard-inf">
          <div class="pcard-nm">{person.name}</div>
          <div class="pcard-rl">{person.title}</div>
        </div>
      {close_tag}"""


def build_people(issue: Issue, page_num: int) -> str:
    """Build People in Data page: header, intro, and 4 even headshot boxes (2 x 2)"""
    cards = "".join(person_card(person) for person in issue.people[:4])

    return f"""
    <div class="pg pg-people">
      <div class="ppl-in">
        <div class="ppl-hdr">
          <div>
            <div class="ppl-iss">{issue.number} · Feature</div>
            <div class="ppl-title">The <em>People</em><br>in Data</div>
          </div>
          <div class="ppl-pgn">{page_num:02d}</div>
        </div>
        <div class="ppl-intro">So if you’re wondering why the first issue of a data magazine revolves around people is because 
        <strong> working with data wouldn’t be as fun if not for the people you meet!!</strong> 
        </div>
        <div class="ppl-grid">{cards}</div>
      </div>
      {page_foot(issue, page_num)}
    </div>"""


def build_meet_editor(issue: Issue, page_num: int) -> str:
    loaded = load_figure_image(EDITOR_PAGE_IMAGE, 1100)
    if loaded:
        img = f'<img src="{loaded[0]}" alt="Meet the Editor: Evelyn">'
    else:
        img = (f'<div class="fig-ph" style="aspect-ratio:4/5"><span>🖼️</span>'
               f'{html_lib.escape(EDITOR_PAGE_IMAGE)} not found</div>')
    button = ""
    if EDITOR_LINKEDIN_URL.strip() and "your-handle" not in EDITOR_LINKEDIN_URL.lower():
        href = html_lib.escape(normalize_url(EDITOR_LINKEDIN_URL), quote=True)
        button = (f'<div class="meet-cta"><a class="app-btn" href="{href}" target="_blank" '
                  f'rel="noopener noreferrer">{html_lib.escape(EDITOR_LINKEDIN_LABEL)}</a></div>')
    return f"""
    <div class="pg pg-meet">
      <div class="meet-img">{img}</div>
      {button}
      {page_foot(issue, page_num)}
    </div>"""


def render_figure(fig: ImageBlock) -> str:
    """One picture as a <figure>; shows a labelled placeholder until the file exists"""
    caption = f"<figcaption>{inline_format(fig.caption)}</figcaption>" if fig.caption else ""
    if fig.src:
        picture = f'<img src="{fig.src}" alt="{html_lib.escape(fig.caption or fig.label, quote=True)}">'
    else:
        picture = (f'<div class="fig-ph" style="aspect-ratio:{fig.aspect:.3f}">'
                   f'<span>🖼️</span>{html_lib.escape(fig.label)}</div>')
    width = fig.width + (POLAROID_PAD if fig.layout == "polaroid" else 0)
    extra = " no-cap" if not fig.caption else ""
    return (f'<figure class="art-fig fig-{fig.layout}{extra}" style="width:{width:.0f}px">'
            f'{picture}{caption}</figure>')


def render_blocks(blocks: list) -> str:
    """Turn parsed ("p"/"sub"/"img", content) blocks into HTML"""
    parts = []
    for kind, text in blocks:
        if kind == "sub":
            parts.append(f'<h3 class="art-sub">{inline_format(text)}</h3>')
        elif kind == "img":
            parts.append(render_figure(text))
        else:
            parts.append(f"<p>{inline_format(text)}</p>")
    return "".join(parts)


def build_article_opener(issue: Issue, art: LoadedArticle, blocks, page_num: int) -> str:
    """First page of an article: title, byline, lead, then body text"""
    title_cls = "art-title long" if len(art.title) > 70 else "art-title"
    byline = f'<div class="art-by">{inline_format(art.byline)}</div>' if art.byline else ""
    lead = f'<div class="art-lead">{inline_format(art.lead)}</div>' if art.lead else ""
    return f"""
    <div class="pg pg-article">
      <div class="art-in">
        <div class="art-tag">{art.label} {art.number}</div>
        <div class="{title_cls}">{inline_format(art.title)}</div>
        {byline}
        {lead}
        <div class="art-body first">{render_blocks(blocks)}</div>
      </div>
      {page_foot(issue, page_num)}
    </div>"""


def build_article_continue(issue: Issue, art: LoadedArticle, blocks, show_quote: bool, page_num: int) -> str:
    """Later pages of an article: body text and (on the second page) the pull quote"""
    pull = f'<div class="art-pull">“{inline_format(art.pull_quote)}”</div>' if show_quote and art.pull_quote else ""
    return f"""
    <div class="pg pg-article">
      <div class="art-in">
        <div class="art-tag">{art.label} {art.number} · Continued</div>
        <div class="art-body">{render_blocks(blocks)}</div>
        {pull}
      </div>
      {page_foot(issue, page_num)}
    </div>"""


def build_blank_page(issue: Issue, page_num: int, content: str = "") -> str:
    """Blank page with footer; optional raw HTML content to fill it in"""
    return f"""
    <div class="pg pg-blank">
      <div class="blank-in">{content}</div>
      {page_foot(issue, page_num)}
    </div>"""


def build_app_intro(issue: Issue, app: AppFeature, page_num: int, turn_page: bool = False) -> str:
    """
    Intro page of a "split" app: kicker, title, intro text, link to the full app.
    Normally the live app is on the facing page; with turn_page=True the intro sits on a
    right-hand page and the live app is on the next left-hand page (after the turn).
    """
    title_cls = "art-title long" if len(app.title) > 70 else "art-title"
    paragraphs = "".join(f"<p>{inline_format(p.strip())}</p>"
                         for p in re.split(r"\n\s*\n", app.blurb.strip()) if p.strip())
    button = ""
    if not app_url_is_placeholder(app.url):
        href = html_lib.escape(normalize_url(app.url), quote=True)
        button = f'<a class="app-btn" href="{href}" target="_blank" rel="noopener noreferrer">Open full app ↗</a>'
    hint = ""
    if app.layout == "split":
        where = "next page" if turn_page else "facing page"
        hint = f'<div class="app-hint">The live app is on the {where} →</div>'
    return f"""
    <div class="pg pg-article">
      <div class="art-in">
        <div class="art-tag">{inline_format(app.kicker)}</div>
        <div class="{title_cls}">{inline_format(app.title)}</div>
        <div class="art-text">{paragraphs}</div>
        {button}
        {hint}
      </div>
      {page_foot(issue, page_num)}
    </div>"""


def build_app_placeholder(issue: Issue, page_num: int) -> str:
    """Page shown behind (and while turning toward) a live app; the app itself is overlaid by JS"""
    return f"""
    <div class="pg pg-blank">
      <div class="blank-in app-wait">Loading app…</div>
      {page_foot(issue, page_num)}
    </div>"""


def build_video_page(issue: Issue, video: VideoFeature, page_num: int) -> str:
    """
    One page with a YouTube video. The page shows the video's thumbnail; the real
    player is only created when the reader clicks it (see playVideo() in the JS).
    That keeps the player out of the page-turn animation and stops playback
    whenever the reader turns the page.
    """
    vid = youtube_id(video.url)
    if vid:
        thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        player = (f'<div class="vid-box" data-vid="{vid}" onclick="playVideo(this)" role="button" '
                  f'aria-label="Play video" style="background-image:url(\'{thumb}\')">'
                  f'<div class="vid-play"></div></div>')
        button = (f'<a class="app-btn" href="https://www.youtube.com/watch?v={vid}" target="_blank" '
                  f'rel="noopener noreferrer">Watch on YouTube ↗</a>')
    else:
        player = '<div class="vid-box vid-missing">No video yet. Paste a YouTube link into MAGAZINE.videos in the Python file.</div>'
        button = ""
    title_cls = "art-title long" if len(video.title) > 70 else "art-title"
    caption = "".join(f"<p>{inline_format(p.strip())}</p>"
                      for p in re.split(r"\n\s*\n", video.caption.strip()) if p.strip())
    return f"""
    <div class="pg pg-article">
      <div class="art-in">
        <div class="art-tag">{inline_format(video.kicker)}</div>
        <div class="{title_cls}">{inline_format(video.title)}</div>
        {player}
        <div class="art-text">{caption}</div>
        {button}
      </div>
      {page_foot(issue, page_num)}
    </div>"""


def build_image_page(issue: Issue, feat: ImagePages, path: str, page_num: int) -> str:
    """
    One page that is just a picture (plus the normal footer).
    mode="scroll": the picture fills the page width and the reader scrolls down inside the page.
    mode="fit":    the whole picture is shown on the page, never cropped.
    Shows a labelled placeholder until the file exists.
    """
    loaded = load_figure_image(path, 1100)
    if loaded:
        img = f'<img src="{loaded[0]}" alt="{html_lib.escape(feat.title, quote=True)}">'
    else:
        img = f'<div class="fig-ph" style="aspect-ratio:3/4"><span>🖼️</span>{html_lib.escape(path)}</div>'
    mode = feat.mode if feat.mode in ("scroll", "cover") else "fit"
    label = f'<div class="img-label">{inline_format(feat.label)}</div>' if feat.label else ""
    return f"""
    <div class="pg pg-imgpage">
      {label}
      <div class="img-area {mode}">{img}</div>
      {page_foot(issue, page_num)}
    </div>"""


PageBuilder = Callable[[int], str]      # takes a page number, returns that page's HTML


def article_page_builders(issue: Issue, art: LoadedArticle, pages: List[dict]) -> List[Tuple[PageBuilder, bool]]:
    """One (builder, is_blank) per page of an article; the builder takes the page number"""
    builders: List[Tuple[PageBuilder, bool]] = []
    for i, page in enumerate(pages):
        if i == 0:
            builders.append((partial(build_article_opener, issue, art, page["blocks"]), False))
        elif page["blocks"] or page["quote"]:
            builders.append((partial(build_article_continue, issue, art, page["blocks"], page["quote"]), False))
        else:
            builders.append((partial(build_blank_page, issue), True))
    return builders


# ═══════════════════════════════════════════════════════════════════════════
# 8. STYLES
# ═══════════════════════════════════════════════════════════════════════════

STYLES = """
  :root {
    --bg:#faf7f2; --ink:#1c1814; --accent:#c94f28;
    --gold:#c49a2a; --green:#2a6e4e;
    --muted:#9a9088; --border:#ddd5c8; --white:#ffffff;
    --pw:__PW__px; --ph:__PH__px; --body-font:__BODYFONT__px;
    --nx-font:'__NXFONT__',serif;
    --art-font:__ARTFONT__px; --art-lh:__ARTLH__; --cols:__COLS__; --col-gap:__COLGAP__px; --para-gap:__PARAGAP__px; --art-align:__ARTALIGN__;
  }
  *{margin:0;padding:0;box-sizing:border-box;}
  html,body{height:100%;}
  body{
    background:radial-gradient(ellipse at 50% 40%,#d8d0c4,#b8ae9e);
    font-family:'Instrument Sans',sans-serif;
    color:var(--ink); overflow:hidden;
  }
  /* #fit holds the whole book at its natural size; JS scales it to the window */
  #fitbox{width:100%;overflow:hidden;}
  #fit{display:flex;flex-direction:column;align-items:center;padding:20px 16px 28px;transform-origin:top left;}
  .hdr{text-align:center;margin-bottom:14px;}
  .hdr-name{font-family:'Fraunces',serif;font-size:13px;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:#7a7060;}
  .hdr-sub{font-size:10px;color:#9a9080;letter-spacing:.1em;margin-top:2px;}

  /* Book */
  .scene{perspective:2400px;width:calc(var(--pw)*2);height:var(--ph);position:relative;margin-bottom:8px;transition:transform .7s cubic-bezier(.645,.045,.355,1);}
  .scene::after{content:'';position:absolute;left:50%;top:0;bottom:0;width:5px;transform:translateX(-50%);background:linear-gradient(to right,rgba(0,0,0,.2),rgba(0,0,0,.05),rgba(0,0,0,.2));z-index:20;pointer-events:none;border-radius:1px;}
  .shadow{width:calc(var(--pw)*2);height:18px;background:radial-gradient(ellipse at 50% 0,rgba(0,0,0,.28),transparent 70%);transition:transform .7s cubic-bezier(.645,.045,.355,1);}
  .p-static{position:absolute;top:0;width:var(--pw);height:var(--ph);overflow:hidden;}
  .p-static.left{left:0;border-radius:5px 0 0 5px;box-shadow:-6px 6px 28px rgba(0,0,0,.18);}
  .p-static.right{right:0;border-radius:0 5px 5px 0;box-shadow:6px 6px 28px rgba(0,0,0,.18);}
  .p-flip{position:absolute;top:0;width:var(--pw);height:var(--ph);transform-style:preserve-3d;transform-origin:left center;z-index:8;display:none;}
  .p-face{position:absolute;inset:0;backface-visibility:hidden;-webkit-backface-visibility:hidden;overflow:hidden;}
  .p-face.front{border-radius:0 5px 5px 0;}
  .p-face.back{transform:rotateY(180deg);border-radius:5px 0 0 5px;}
  .p-flip.fwd .p-face.front::after,.p-flip.bck .p-face.back::after{content:'';position:absolute;inset:0;background:linear-gradient(to left,rgba(0,0,0,.12),transparent 40%);pointer-events:none;}
  @keyframes fwd{from{transform:rotateY(0)}to{transform:rotateY(-180deg)}}
  @keyframes bck{from{transform:rotateY(-180deg)}to{transform:rotateY(0)}}
  .p-flip.fwd{animation:fwd .9s cubic-bezier(.645,.045,.355,1) forwards;}
  .p-flip.bck{animation:bck .9s cubic-bezier(.645,.045,.355,1) forwards;}

  /* Pages */
  .pg{width:100%;height:100%;background:var(--bg);overflow:hidden;font-size:13px;position:relative;}

  /* Cover photo page — full bleed, no padding, no background */
  .pg-cover-photo{background:var(--ink);padding:0;overflow:hidden;}
  .pg-cover-back{background:var(--ink);}

  /* Next-issue page (inside of the back cover) */
  .pg-next{background:var(--ink);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:40px;}
  .pg-next::before{content:'';position:absolute;width:280px;height:280px;border-radius:50%;border:1px solid rgba(255,255,255,.05);top:-80px;left:-70px;pointer-events:none;}
  .nx-kicker{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:600;}
  .nx-name{font-family:var(--nx-font);font-size:15px;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:var(--bg);margin-top:10px;}
  .nx-will{font-family:var(--nx-font);font-style:italic;font-size:15px;color:#aea6a0;margin:24px 0 6px;}
  .nx-head{font-family:var(--nx-font);font-size:58px;font-weight:900;line-height:1;letter-spacing:-.025em;color:var(--bg);}
  .nx-head em{font-style:italic;color:var(--accent);}

  /* Back cover */
  .pg-back{background:var(--ink);padding:44px 38px 36px;display:flex;flex-direction:column;justify-content:space-between;text-align:center;}
  .pg-back::before{content:'';position:absolute;width:300px;height:300px;border-radius:50%;border:1px solid rgba(255,255,255,.05);bottom:-90px;right:-80px;pointer-events:none;}
  .bk-tag{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:600;}
  .bk-mid{display:flex;flex-direction:column;align-items:center;}
  .bk-head{font-family:'Fraunces',serif;font-size:38px;font-weight:900;line-height:1.02;letter-spacing:-.025em;color:var(--bg);}
  .bk-head em{font-style:italic;color:var(--accent);}
  .bk-rule{width:36px;height:2px;background:var(--accent);margin:22px 0;}
  .bk-tagline{font-family:'Fraunces',serif;font-style:italic;font-size:14px;line-height:1.5;color:#aea6a0;max-width:260px;}
  .bk-name{font-family:'Fraunces',serif;font-size:13px;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:var(--bg);}
  .bk-sub{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin-top:4px;}
  .bk-btn{margin-top:26px;font-family:'Instrument Sans',sans-serif;font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--bg);background:transparent;border:1px solid rgba(255,255,255,.3);padding:9px 18px;border-radius:20px;cursor:pointer;transition:all .2s;}
  .bk-btn:hover{background:var(--accent);border-color:var(--accent);}
  .bk-ph{width:100%;padding:34px 20px;border:1px dashed rgba(255,255,255,.22);background:#2e2820;display:flex;flex-direction:column;align-items:center;gap:8px;}
  .bk-ph-lb{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:rgba(255,255,255,.55);}
  .bk-ph-hint{font-size:10px;line-height:1.5;color:var(--muted);}

  /* Cover-solo mode: center single cover page, hide right page and spine */
  .scene.cover-solo{transform:translateX(calc(var(--pw) / 2));}
  .scene.cover-solo::after{display:none;}
  .scene.cover-solo .p-static.left{border-radius:5px;box-shadow:0 8px 36px rgba(0,0,0,.28);}
  .scene.cover-solo #sr{visibility:hidden;}
  .shadow.cover-solo{transform:translateX(calc(var(--pw) / 2));}

  /* Back-solo mode: the book closes. Centre the back cover, hide the left page and spine */
  .scene.back-solo{transform:translateX(calc(var(--pw) / -2));}
  .scene.back-solo::after{display:none;}
  .scene.back-solo .p-static.right{border-radius:5px;box-shadow:0 8px 36px rgba(0,0,0,.28);}
  .scene.back-solo #sl{visibility:hidden;}
  .shadow.back-solo{transform:translateX(calc(var(--pw) / -2));}

  /* Letter: photo + headline on top, text beside a second photo, signature below */
  .pg-letter{background:var(--ink);padding:32px 30px 22px;display:flex;flex-direction:column;}
  .pg-letter::before{content:'';position:absolute;width:280px;height:280px;border-radius:50%;border:1px solid rgba(255,255,255,.04);bottom:-80px;left:-70px;pointer-events:none;}
  .ltr-top{display:flex;gap:18px;align-items:flex-start;margin-bottom:16px;flex-shrink:0;}
  .ltr-titleblock{flex:1;min-width:0;padding-top:2px;}
  .ltr-tag{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:7px;}
  .ltr-tag::before{content:'';width:14px;height:1px;background:var(--accent);display:block;}
  .ltr-head{font-family:'Fraunces',serif;font-size:30px;font-weight:900;line-height:1.0;letter-spacing:-.025em;color:var(--bg);}
  .ltr-head em{font-style:italic;color:var(--accent);}
  .ltr-img{overflow:hidden;flex-shrink:0;background:#2e2820;border:1px solid rgba(255,255,255,.14);display:flex;flex-direction:column;align-items:center;justify-content:center;}
  .ltr-img img{width:100%;height:100%;object-fit:cover;display:block;}
  .ltr-img-a{width:130px;height:172px;}
  .ltr-img-b{width:100%;height:236px;}
  .ltr-mid{display:flex;gap:18px;flex:1;min-height:0;}
  .ltr-body{flex:1;min-width:0;overflow:hidden;font-size:11px;line-height:1.7;color:#aea6a0;font-weight:300;}
  .ltr-body strong{color:var(--bg);font-weight:500;}
  .ltr-side{width:210px;flex-shrink:0;display:flex;flex-direction:column;gap:10px;}
  .ltr-note{border-left:3px solid var(--accent);background:rgba(255,255,255,.06);padding:11px 14px;}
  .ltr-note-t{font-family:'Fraunces',serif;font-size:15px;font-weight:700;font-style:italic;color:var(--bg);line-height:1.15;}
  .ltr-note-s{font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-top:4px;}
  /* Film-strip photo: shown whole (never cropped), centred in the side column */
  .ltr-side.has-strip{align-items:center;}
  .ltr-strip{flex-shrink:0;border-radius:3px;overflow:hidden;background:#000;box-shadow:0 4px 14px rgba(0,0,0,.45);}
  .ltr-strip img{display:block;width:100%;height:auto;}
  .ltr-strip-ph{display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px dashed rgba(255,255,255,.2);background:#2e2820;}
  .ltr-sig{border-top:1px solid rgba(255,255,255,.1);padding-top:12px;margin-top:14px;display:flex;align-items:center;gap:14px;flex-shrink:0;}
  .ltr-photo{width:56px;height:56px;border-radius:50%;overflow:hidden;flex-shrink:0;border:2px solid var(--accent);background:#2e2820;display:flex;flex-direction:column;align-items:center;justify-content:center;}
  .ltr-photo img{width:100%;height:100%;object-fit:cover;display:block;}
  .ltr-ph-ic{font-size:22px;opacity:.45;}
  .ltr-ph-lb{font-size:6px;color:rgba(255,255,255,.3);text-transform:uppercase;letter-spacing:.05em;text-align:center;line-height:1.2;padding:0 6px;word-break:break-all;}
  .ltr-name{font-family:'Fraunces',serif;font-size:16px;font-weight:700;font-style:italic;color:var(--bg);}
  .ltr-role{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-top:2px;}

  /* TOC */
  .pg-toc{padding:32px 28px 24px;display:flex;flex-direction:column;height:100%;}
  .pg-logo{font-family:'Fraunces',serif;font-size:9px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin-bottom:20px;display:flex;align-items:center;gap:8px;}
  .pg-logo::after{content:'';flex:1;height:1px;background:var(--border);}
  .toc-lbl{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);margin-bottom:10px;}
  .toc-row{display:grid;grid-template-columns:18px 1fr 18px;align-items:baseline;gap:8px;padding:10px 0;border-bottom:1px solid var(--border);}
  .toc-row:last-of-type{border-bottom:none;}
  .toc-n{font-family:'Fraunces',serif;font-size:10px;font-weight:700;color:var(--accent);font-style:italic;}
  .toc-t{font-family:'Fraunces',serif;font-size:12px;font-weight:700;color:var(--ink);line-height:1.2;}
  .toc-s{font-size:9px;color:var(--muted);font-weight:300;display:block;margin-top:1px;}
  .toc-p{font-size:9px;color:var(--muted);text-align:right;}
  .toc-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--border);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-top:auto;}
  .ts{background:var(--bg);padding:12px 8px;text-align:center;}
  .ts-n{font-family:'Fraunces',serif;font-size:22px;font-weight:900;color:var(--ink);line-height:1;}
  .ts-n span{color:var(--accent);}
  .ts-l{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:2px;}

  /* Shared footer */
  .pg-foot{height:33px;display:flex;justify-content:space-between;align-items:center;padding:9px 26px;border-top:1px solid var(--border);background:var(--bg);font-size:9px;color:var(--muted);flex-shrink:0;}
  .pg-foot strong{font-family:'Fraunces',serif;font-weight:700;color:var(--ink);font-size:11px;}

  /* People — header + 2x2 grid of equal boxes */
  .pg-people{padding:28px 0 0;display:flex;flex-direction:column;height:100%;}
  .ppl-in{flex:1;min-height:0;padding:0 26px;display:flex;flex-direction:column;}
  .ppl-hdr{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid var(--ink);padding-bottom:10px;margin-bottom:14px;flex-shrink:0;}
  .ppl-iss{font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin-bottom:3px;}
  .ppl-title{font-family:'Fraunces',serif;font-size:28px;font-weight:900;line-height:1;letter-spacing:-.02em;}
  .ppl-title em{font-style:italic;color:var(--accent);}
  .ppl-pgn{font-family:'Fraunces',serif;font-size:36px;font-weight:900;color:var(--border);line-height:1;}
  .ppl-intro{font-size:11px;color:#5a5248;line-height:1.65;font-weight:300;margin-bottom:14px;flex-shrink:0;}
  .ppl-intro strong{color:var(--ink);font-weight:600;}
  .ppl-grid{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:10px;flex:1;min-height:0;margin-bottom:12px;}
  .pcard{background:var(--white);border:1px solid var(--border);border-bottom:3px solid var(--card-accent,var(--accent));border-radius:10px;overflow:hidden;display:flex;flex-direction:column;min-height:0;}
  .pcard-ph{flex:1;min-height:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;overflow:hidden;}
  .pcard-ph img{width:100%;height:100%;object-fit:cover;display:block;}
  .pcard-ph .ic{font-size:28px;opacity:.45;}
  .pcard-ph .lb{font-size:8px;color:rgba(28,24,20,.4);text-transform:uppercase;letter-spacing:.07em;text-align:center;line-height:1.3;padding:0 8px;}
  .pcard-inf{padding:8px 10px 9px;flex-shrink:0;}
  .pcard-nm{font-family:'Fraunces',serif;font-size:13px;font-weight:700;color:var(--ink);line-height:1.1;margin-bottom:3px;}
  .pcard-rl{font-size:8px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);line-height:1.35;}

  .pcard{color:inherit;text-decoration:none;}
  .pcard-ph{position:relative;}
  .pcard.has-link{cursor:pointer;transition:transform .2s,box-shadow .2s;}
  .pcard.has-link:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(0,0,0,.16);}
  .pcard-in{position:absolute;top:6px;right:6px;font-size:8px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;background:rgba(28,24,20,.78);color:var(--bg);padding:3px 7px;border-radius:10px;}

  /* Meet the Editor page: picture shown whole, LinkedIn button underneath */
  .pg-meet{display:flex;flex-direction:column;height:100%;background:#f5f4f0;}
  .meet-img{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;overflow:hidden;}
  .meet-img img{width:100%;height:100%;object-fit:contain;display:block;}
  .meet-cta{flex-shrink:0;text-align:center;padding:4px 0 10px;}
  .meet-cta .app-btn{margin-top:0;background:var(--accent);}
  .meet-cta .app-btn:hover{background:var(--ink);}

  /* Articles */
  .pg-article{padding:30px 0 0;display:flex;flex-direction:column;height:100%;}
  .art-in{flex:1;min-height:0;padding:0 26px;overflow:hidden;}
  .art-tag{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:600;margin-bottom:10px;display:flex;align-items:center;gap:7px;}
  .art-tag::before{content:'';width:14px;height:1px;background:var(--accent);display:block;}
  .art-title{font-family:'Fraunces',serif;font-size:26px;font-weight:900;line-height:1.08;letter-spacing:-.02em;color:var(--ink);margin-bottom:10px;}
  .art-title.long{font-size:17px;line-height:1.2;letter-spacing:-.01em;}
  .art-by{font-size:10px;color:var(--muted);letter-spacing:.06em;text-transform:uppercase;padding-bottom:12px;border-bottom:2px solid var(--ink);margin-bottom:14px;line-height:1.4;}
  .art-lead{font-family:'Fraunces',serif;font-size:13px;font-style:italic;line-height:1.55;color:#5a5248;margin-bottom:12px;}
  .art-text p{font-size:var(--body-font);line-height:1.75;color:#3a342c;font-weight:300;margin-bottom:10px;}
  .art-text strong{font-weight:600;color:var(--ink);}
  .art-sub{font-family:'Fraunces',serif;font-size:14px;font-weight:700;line-height:1.2;color:var(--ink);margin:14px 0 6px;}
  .art-pull{font-family:'Fraunces',serif;font-size:16px;font-weight:700;font-style:italic;line-height:1.3;color:var(--ink);border-left:3px solid var(--accent);padding-left:12px;margin:16px 0 8px;}

  /* Article body: magazine columns (balanced, so an overrun clips the page bottom instead of adding a column) */
  .art-body{column-count:var(--cols);column-gap:var(--col-gap);column-rule:1px solid var(--border);column-fill:balance;}
  .art-body p{font-size:var(--art-font);line-height:var(--art-lh);color:#3a342c;font-weight:300;margin-bottom:var(--para-gap);text-align:var(--art-align);hyphens:auto;-webkit-hyphens:auto;overflow-wrap:break-word;orphans:2;widows:2;}
  .art-body strong{font-weight:600;color:var(--ink);}
  .art-body .art-sub{break-after:avoid;break-inside:avoid;}
  .art-body > :first-child{margin-top:0;}
  .art-body.first > p:first-child::first-letter{float:left;font-family:'Fraunces',serif;font-weight:900;font-size:40px;line-height:.9;padding:3px 6px 0 0;color:var(--accent);}

  /* Pictures inside articles */
  .art-fig{margin:4px 0 10px;break-inside:avoid;-webkit-column-break-inside:avoid;}
  .art-fig img{display:block;width:100%;height:auto;}
  .art-fig figcaption{font-size:9.5px;line-height:1.4;color:var(--muted);font-style:italic;margin-top:5px;text-align:left;hyphens:none;}
  .fig-ph{width:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;background:#ece6da;border:1px dashed var(--border);font-size:8px;color:var(--muted);text-align:center;letter-spacing:.05em;text-transform:uppercase;word-break:break-all;padding:0 8px;}

  .fig-banner,.fig-feature{column-span:all;-webkit-column-span:all;margin:6px auto 14px;}
  .fig-banner img,.fig-feature img{box-shadow:0 2px 8px rgba(0,0,0,.14);}
  .fig-banner figcaption,.fig-feature figcaption{text-align:center;}
  .fig-feature{margin:10px auto 16px;}

  .fig-column img{border-bottom:3px solid var(--accent);}

  .fig-inset{float:right;margin:2px 0 6px 10px;}
  .fig-inset img{border-top:3px solid var(--accent);}

  .fig-polaroid{background:#fff;padding:8px 8px 10px;border:1px solid var(--border);box-shadow:0 4px 12px rgba(0,0,0,.2);transform:rotate(-1.4deg);margin:8px auto 14px;}
  .fig-polaroid.no-cap{padding-bottom:26px;}
  .fig-polaroid figcaption{font-family:'Fraunces',serif;font-size:10px;color:#5a5248;text-align:center;margin-top:7px;}

  /* Streamlit app pages */
  .app-btn{display:inline-block;margin-top:6px;font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--bg);background:var(--ink);padding:9px 18px;border-radius:20px;text-decoration:none;}
  .app-btn:hover{background:var(--accent);}
  .app-hint{margin-top:14px;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);}
  .app-wait{display:flex;align-items:center;justify-content:center;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);}
  #appHost{position:absolute;top:0;height:calc(var(--ph) - 33px);z-index:10;display:none;background:#fff;overflow:hidden;}
  .app-wrap{display:none;flex-direction:column;width:100%;height:100%;}
  .app-bar{height:30px;flex-shrink:0;background:var(--ink);color:var(--bg);display:flex;align-items:center;justify-content:space-between;padding:0 14px;font-size:10px;letter-spacing:.1em;text-transform:uppercase;}
  .app-bar a{color:#e9a48d;text-decoration:none;font-weight:600;}
  .app-wrap iframe{flex:1;min-height:0;width:100%;border:0;background:#fff;}
  .app-missing{flex:1;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;font-size:12px;line-height:1.6;color:#5a5248;background:var(--bg);}

  /* YouTube video page */
  .vid-box,.vid-frame{display:block;width:100%;aspect-ratio:16/9;border:0;border-radius:8px;background:#000 center/cover no-repeat;position:relative;cursor:pointer;margin:6px 0 14px;}
  .vid-frame{cursor:default;}
  .vid-play{position:absolute;left:50%;top:50%;width:58px;height:58px;margin:-29px 0 0 -29px;border-radius:50%;background:rgba(201,79,40,.92);}
  .vid-play::after{content:'';position:absolute;left:23px;top:17px;border-left:18px solid #fff;border-top:12px solid transparent;border-bottom:12px solid transparent;}
  .vid-box:hover .vid-play{background:var(--accent);}
  .vid-missing{display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;font-size:12px;line-height:1.6;color:#5a5248;background:var(--white);border:1px dashed var(--border);cursor:default;}

  /* Picture pages (infographic spread, ads) */
  .pg-imgpage{display:flex;flex-direction:column;height:100%;background:var(--white);}
  .img-label{flex-shrink:0;text-align:center;font-size:9px;font-weight:600;letter-spacing:.24em;text-transform:uppercase;color:var(--muted);padding:9px 0 7px;background:var(--bg);}
  .img-area{flex:1;min-height:0;overflow:hidden;background:var(--bg);}
  .img-area img{display:block;width:100%;}
  .img-area.scroll{overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;background:var(--white);}
  .img-area.scroll img{height:auto;}
  .img-area.fit img{height:100%;object-fit:contain;object-position:bottom;}
  .img-area.cover img{height:100%;object-fit:cover;object-position:center;}

  /* Blank pages */
  .pg-blank{padding:30px 0 0;display:flex;flex-direction:column;height:100%;}
  .blank-in{flex:1;min-height:0;padding:0 26px;overflow:hidden;font-size:var(--body-font);line-height:1.75;color:#3a342c;}

  /* Nav */
  .nav-top{display:flex;align-items:center;justify-content:center;gap:16px;margin-bottom:12px;}
  .nav-btn{background:rgba(255,255,255,.22);border:1px solid rgba(255,255,255,.28);color:#4a4038;font-family:'Instrument Sans',sans-serif;font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;padding:10px 22px;border-radius:24px;cursor:pointer;transition:all .2s;}
  .nav-btn:hover:not(:disabled){background:rgba(255,255,255,.4);color:var(--ink);}
  .nav-btn:disabled{opacity:.28;cursor:default;}
  .dots{display:flex;gap:6px;align-items:center;}
  .dot{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.3);cursor:pointer;transition:all .3s;}
  .dot.on{background:rgba(255,255,255,.82);width:18px;border-radius:3px;}
  .nav-lbl{font-size:10px;color:#7a7060;letter-spacing:.1em;text-transform:uppercase;text-align:center;min-height:15px;margin-bottom:10px;}
"""


# ═══════════════════════════════════════════════════════════════════════════
# 9. JAVASCRIPT (Page flip logic)
# ═══════════════════════════════════════════════════════════════════════════

# __SPREADS__ is replaced with the spread list generated in Python (section 10),
# so adding or removing pages never requires editing this JavaScript.
JAVASCRIPT = """
const spreads = __SPREADS__;
let cur = 0, busy = false;
let target = null;          // set while goTo() is travelling across several spreads
const appEls = {};          // live app wrappers, kept per spread so app state survives page turns

function makeApp(a) {
  const wrap = document.createElement('div');
  wrap.className = 'app-wrap';
  const bar = document.createElement('div');
  bar.className = 'app-bar';
  const title = document.createElement('span');
  title.textContent = a.title;
  bar.appendChild(title);
  if (a.open_url) {
    const link = document.createElement('a');
    link.href = a.open_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    link.textContent = 'Open full app \u2197';
    bar.appendChild(link);
  }
  wrap.appendChild(bar);
  if (a.embed_url) {
    const frame = document.createElement('iframe');
    frame.src = a.embed_url; frame.title = a.title; frame.allow = 'clipboard-write';
    wrap.appendChild(frame);
  } else {
    const msg = document.createElement('div');
    msg.className = 'app-missing';
    msg.textContent = 'No app URL set yet. Add the deployed Streamlit URL to MAGAZINE.apps in the Python file.';
    wrap.appendChild(msg);
  }
  return wrap;
}

// Swap a video thumbnail for the real YouTube player (privacy-enhanced domain)
function playVideo(box) {
  const frame = document.createElement('iframe');
  frame.className = 'vid-frame';
  frame.src = 'https://www.youtube-nocookie.com/embed/' + box.dataset.vid + '?autoplay=1&rel=0&playsinline=1';
  frame.title = 'Video player';
  frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen';
  frame.allowFullscreen = true;
  frame.referrerPolicy = 'strict-origin-when-cross-origin';
  box.replaceWith(frame);
}

function hideApp() { document.getElementById('appHost').style.display = 'none'; }

function showApp() {
  const host = document.getElementById('appHost');
  const a = spreads[cur].app;
  if (!a) { hideApp(); return; }
  const full = a.layout === 'full';
  host.style.left = (full || a.side === 'left') ? '0' : 'var(--pw)';
  host.style.width = full ? 'calc(var(--pw) * 2)' : 'var(--pw)';
  Array.from(host.children).forEach(c => c.style.display = 'none');
  if (!appEls[cur]) { appEls[cur] = makeApp(a); host.appendChild(appEls[cur]); }
  appEls[cur].style.display = 'flex';
  host.style.display = 'block';
}
const sl=document.getElementById('sl'), sr=document.getElementById('sr');
const fp=document.getElementById('fp'), ff=document.getElementById('ff'), fb=document.getElementById('fb');

function html(id) {
  const t = document.getElementById(id);
  return t ? t.innerHTML : '<div class="pg" style="display:flex;align-items:center;justify-content:center;color:#aaa">Coming soon</div>';
}

function init() { 
  sl.innerHTML=html(spreads[cur].p[0]); 
  sr.innerHTML=html(spreads[cur].p[1]); 
  fp.style.display='none'; 
  sync(); 
}

function turn(dir) {
  if (busy) return;
  const next = cur + dir;
  if (next < 0 || next >= spreads.length) return;
  busy = true;
  hideApp();
  fp.className = 'p-flip';
  
  if (dir > 0) {
    sr.innerHTML = html(spreads[next].p[1]);
    ff.innerHTML = html(spreads[cur].p[1]);
    fb.innerHTML = html(spreads[next].p[0]);
    fp.style.left = 'var(--pw)'; 
    fp.style.transformOrigin = 'left center';
    fp.style.transform = 'rotateY(0)'; 
    fp.style.display = 'block';
    void fp.offsetWidth; 
    fp.classList.add('fwd');
    fp.addEventListener('animationend', () => { 
      fp.style.display='none'; 
      fp.className='p-flip'; 
      sl.innerHTML=html(spreads[next].p[0]); 
      cur=next; 
      busy=false; 
      sync(); 
    }, {once:true});
  } else {
    sl.innerHTML = html(spreads[next].p[0]);
    ff.innerHTML = html(spreads[cur].p[0]);
    fb.innerHTML = html(spreads[next].p[1]);
    fp.style.left = 'var(--pw)'; 
    fp.style.transformOrigin = 'left center';
    fp.style.transform = 'rotateY(-180deg)'; 
    fp.style.display = 'block';
    void fp.offsetWidth; 
    fp.classList.add('bck');
    fp.addEventListener('animationend', () => { 
      fp.style.display='none'; 
      fp.className='p-flip'; 
      sr.innerHTML=html(spreads[next].p[1]); 
      cur=next; 
      busy=false; 
      sync(); 
    }, {once:true});
  }
}

function goTo(i) {
  if (busy || i === cur) return;
  target = i;
  const d = i > cur ? 1 : -1;
  const step = () => { 
    if (cur===i) return; 
    const w=()=>{ if(!busy) step(); else setTimeout(w,50); }; 
    turn(d); 
    setTimeout(w,950); 
  };
  step();
}

// Jump straight back to the front cover (no page-by-page flipping)
function restart() {
  if (busy) return;
  hideApp();
  target = null;
  cur = 0;
  init();
}

function sync() {
  document.getElementById('btnF').disabled = cur === 0;
  document.getElementById('btnP').disabled = cur === 0;
  document.getElementById('btnN').disabled = cur === spreads.length - 1;
  document.getElementById('nlbl').textContent = spreads[cur].label;
  document.getElementById('dots').innerHTML = spreads.map((s,i) => `<div class="dot${i===cur?' on':''}" onclick="goTo(${i})"></div>`).join('');
  const isCover = cur === 0;
  const isBack = cur === spreads.length - 1 && spreads.length > 1 && spreads[cur].label === 'Back Cover';
  document.getElementById('scene').classList.toggle('cover-solo', isCover);
  document.getElementById('shadow').classList.toggle('cover-solo', isCover);
  document.getElementById('scene').classList.toggle('back-solo', isBack);
  document.getElementById('shadow').classList.toggle('back-solo', isBack);
  if (target !== null && cur !== target) { hideApp(); } else { target = null; showApp(); }
}

init();

// Scale the whole book to fit the window (width AND height)
const NAT_W = __PW__ * 2 + 96;
function fit() {
  const box = document.getElementById('fitbox'), inner = document.getElementById('fit');
  inner.style.width = NAT_W + 'px';
  const natH = inner.offsetHeight;
  const s = Math.min(window.innerWidth / NAT_W, window.innerHeight / natH);
  inner.style.transform = `translateX(${(window.innerWidth - NAT_W * s) / 2}px) scale(${s})`;
  box.style.height = (natH * s) + 'px';
}
window.addEventListener('resize', fit);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
fit();
"""


# ═══════════════════════════════════════════════════════════════════════════
# 10. FULL HTML ASSEMBLY
# ═══════════════════════════════════════════════════════════════════════════

class PageSlot(NamedTuple):
    """One page of the book after the front matter"""
    build: PageBuilder              # takes the page number, returns the page's HTML
    label: str                      # shown under the page-turn buttons
    app: Optional[dict] = None      # set on the LEFT page of an app spread
    blank: bool = False             # True for filler pages


def plan_pages(issue: Issue) -> Tuple[List[PageSlot], Dict[str, int]]:
    """
    Lay out every page after the front matter, in order.
    Returns (slots, start_pages): slots[0] is page ARTICLE_START_PAGE (a left-hand
    page). start_pages maps each article / appendix number to its first page, plus
    "extras" -> the first video or app page (used by the table of contents).
    """
    slots: List[PageSlot] = []
    start_pages: Dict[str, int] = {}

    def next_page() -> int:
        return ARTICLE_START_PAGE + len(slots)

    def pad_to_left(label: str = "") -> None:
        """If the next page would be right-hand, add a blank page so it starts on the left"""
        if len(slots) % 2:
            slots.append(PageSlot(partial(build_blank_page, issue), label or slots[-1].label, blank=True))

    def add_article(art: LoadedArticle, pages: List[dict]) -> int:
        if ARTICLES_START_ON_LEFT:
            pad_to_left()
        start_page = next_page()
        label = f"{art.label} {art.number}"
        for build, is_blank in article_page_builders(issue, art, pages):
            slots.append(PageSlot(build, label, blank=is_blank))
        return start_page

    def add_app(app: AppFeature) -> None:
        missing = app_url_is_placeholder(app.url)
        layout = app.layout if app.layout in ("split", "full") else "split"
        label = f"{app.kicker} · {app.title}"
        info = {
            "title": app.title,
            "layout": layout,
            "side": "right",
            "embed_url": None if missing else streamlit_embed_url(app.url),
            "open_url": None if missing else normalize_url(app.url),
        }
        if layout == "split" and len(slots) % 2:
            # The next page is right-hand. Instead of leaving it blank, put the intro there
            # and show the live app on the left-hand page after the turn.
            start_pages.setdefault("extras", next_page())
            slots.append(PageSlot(partial(build_app_intro, issue, app, turn_page=True), label))
            slots.append(PageSlot(partial(build_app_placeholder, issue), label, app={**info, "side": "left"}))
            return
        pad_to_left()                              # "full" apps need both pages of a spread
        start_pages.setdefault("extras", next_page())
        left = (partial(build_app_intro, issue, app) if layout == "split"
                else partial(build_app_placeholder, issue))
        slots.append(PageSlot(left, label, app=info))
        slots.append(PageSlot(partial(build_app_placeholder, issue), label))

    def add_video(video: VideoFeature) -> None:
        start_pages.setdefault("extras", next_page())
        slots.append(PageSlot(partial(build_video_page, issue, video), f"{video.kicker} · {video.title}"))

    def add_image_group(group: List[ImagePages]) -> None:
        """
        Place picture pages that share the same `after`. A two-page spread must start on a
        left-hand page. If the next page is right-hand, a one-page picture goes there first
        (so no blank page is needed before the spread); otherwise they stay in the order listed.
        """
        group = list(group)
        if len(slots) % 2:
            group.sort(key=lambda f: len(f.files) != 1)      # stable: one-page pictures first
        for feat in group:
            if len(feat.files) > 1:
                pad_to_left()
            if feat.toc_key:
                start_pages[feat.toc_key] = next_page()    # lets a TOC entry (page_of=toc_key) show this page
            for path in feat.files:
                slots.append(PageSlot(partial(build_image_page, issue, feat, path), feat.title))

    # 1) Read + paginate every article first so the TOC can show real page numbers
    loaded = [load_article(a) for a in issue.articles]
    layouts = [layout_article(a) for a in loaded]
    back = [load_article(a) for a in issue.appendix]
    back_layouts = [layout_article(a) for a in back]

    # 2) Order of the middle of the book: articles, with app, video and picture pages slotted in
    known = {a.number for a in issue.articles}

    def extras(after: str) -> list:
        # when a video and an app share the same `after`, the video comes first;
        # picture pages come after both
        out = ([("video", v) for v in issue.videos if v.after == after]
               + [("app", a) for a in issue.apps if a.after == after])
        group = [p for p in issue.pages if p.after == after]
        return out + ([("pages", group)] if group else [])

    items = extras("")
    for i, art in enumerate(loaded):
        items.append(("article", i))
        items += extras(art.number)
    items += [("app", a) for a in issue.apps if a.after and a.after not in known]
    items += [("video", v) for v in issue.videos if v.after and v.after not in known]
    stray = [p for p in issue.pages if p.after and p.after not in known]
    if stray:
        items.append(("pages", stray))

    for kind, x in items:
        if kind == "article":
            start_pages[loaded[x].number] = add_article(loaded[x], layouts[x])
        elif kind == "app":
            add_app(x)
        elif kind == "pages":
            add_image_group(x)
        else:
            add_video(x)

    # 3) Appendix, then the blank Notes spreads
    for art, pages in zip(back, back_layouts):
        start_pages[art.number] = add_article(art, pages)

    pad_to_left("Notes")
    notes_first_page = next_page()
    for _ in range(NUM_BLANK_SPREADS):
        for _side in range(2):
            n = next_page() - notes_first_page + 1
            slots.append(PageSlot(partial(build_blank_page, issue, content=BLANK_PAGE_CONTENT.get(n, "")),
                                  "Notes", blank=True))
    pad_to_left("Notes")                           # the book must end on a full spread
    return slots, start_pages


def build_spreads(issue: Issue, cover_src: str) -> List[tuple]:
    """
    Build the ordered list of spreads as (left_html, right_html, label, app).
    Page numbers are derived from position: spread N holds pages 2N+1 and 2N+2.
    To reorder or add pages, change plan_pages() above.
    """
    slots, start_pages = plan_pages(issue)

    spreads = [
        (build_cover_page(cover_src), build_cover_back(), "Cover", None),
        (build_editor_letter(issue), build_toc(issue, start_pages), "Editor's Letter & Table of Contents", None),
        (build_people(issue, 5), build_meet_editor(issue, 6), "People in Data & Meet the Editor", None),
    ]
    for i in range(0, len(slots), 2):
        left, right = slots[i], slots[i + 1]
        page = ARTICLE_START_PAGE + i
        label = left.label if left.label == right.label else f"{left.label} · {right.label}"
        spreads.append((left.build(page), right.build(page + 1), label, left.app))
    if NEXT_ISSUE:
        # the "next issue" page gets a spread of its own, so it stays put and can be read
        spreads.append((build_next_issue_page(issue), build_cover_back(), "Next Issue", None))
    if SHOW_BACK_COVER:
        # inside of the back cover (hidden when the book closes) + the back cover itself
        spreads.append((build_cover_back(), build_back_cover(issue), "Back Cover", None))
    return spreads


def describe_pages(issue: Issue) -> str:
    """Plain-text page map (page number -> what is on it). Shown when SHOW_PAGE_MAP is True."""
    slots, _ = plan_pages(issue)
    lines = ["p.01-02  Cover", "p.03-04  Editor's Letter & Table of Contents", "p.05-06  People in Data & Meet the Editor"]
    for i, slot in enumerate(slots):
        lines.append(f"p.{ARTICLE_START_PAGE + i:02d}     {slot.label}" + ("   <-- BLANK" if slot.blank else ""))
    if NEXT_ISSUE:
        lines.append("         Next Issue page (+ a dark page)")
    if SHOW_BACK_COVER:
        lines.append("         Back Cover (inside back cover + back cover)")
    return "\n".join(lines)


def build_full_html(issue: Issue, cover_src: str) -> str:
    """Assemble complete HTML document"""
    spreads = build_spreads(issue, cover_src)

    # One <template> per page (T0, T1, ...) plus the JS spread map
    templates = ""
    spread_map = []
    for i, (left, right, label, app) in enumerate(spreads):
        templates += f'<template id="T{2*i}">{left}</template>\n'
        templates += f'<template id="T{2*i+1}">{right}</template>\n'
        spread_map.append({"p": [f"T{2*i}", f"T{2*i+1}"], "label": label, "app": app})

    js = (JAVASCRIPT.replace("__SPREADS__", json.dumps(spread_map).replace("</", "<\\/"))
          .replace("__PW__", str(PAGE_W)))
    css = (STYLES.replace("__PW__", str(PAGE_W)).replace("__PH__", str(PAGE_H))
           .replace("__BODYFONT__", str(BODY_FONT_PX))
           .replace("__ARTFONT__", str(ART_FONT_PX)).replace("__ARTLH__", str(ART_LINE_HEIGHT))
           .replace("__COLS__", str(ARTICLE_COLUMNS)).replace("__COLGAP__", str(COLUMN_GAP_PX))
           .replace("__PARAGAP__", str(PARA_GAP_PX))
           .replace("__NXFONT__", NEXT_ISSUE_FONT.replace("'", "").strip() or "Fraunces")
           .replace("__ARTALIGN__", "justify" if ARTICLE_JUSTIFY else "left"))

    nx_font = NEXT_ISSUE_FONT.replace("'", "").strip()
    extra_font = "" if nx_font in ("", "Fraunces", "Instrument Sans") else f"&family={nx_font.replace(' ', '+')}"
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,700;0,9..144,900;1,9..144,700&family=Instrument+Sans:wght@300;400;500;600{extra_font}&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div id="fitbox"><div id="fit">

<div class="hdr">
  <div class="hdr-name">Data World Magazine</div>
  <div class="hdr-sub">{issue.number} · {issue.year} · {issue.theme}</div>
</div>

<div class="nav-top">
  <button class="nav-btn" id="btnF" onclick="restart()">↺ Front</button>
  <button class="nav-btn" id="btnP" onclick="turn(-1)">← Prev</button>
  <div class="dots" id="dots"></div>
  <button class="nav-btn" id="btnN" onclick="turn(1)">Next →</button>
</div>

<div class="nav-lbl" id="nlbl"></div>

<div class="scene" id="scene">
  <div class="p-static left"  id="sl"></div>
  <div class="p-static right" id="sr"></div>
  <div class="p-flip" id="fp">
    <div class="p-face front" id="ff"></div>
    <div class="p-face back"  id="fb"></div>
  </div>
  <div id="appHost"></div>
</div>
<div class="shadow" id="shadow"></div>

</div></div>

{templates}

<script>{js}</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════
# 11. STREAMLIT RENDER
# ═══════════════════════════════════════════════════════════════════════════

cover_src = load_cover_image()
magazine_html = build_full_html(MAGAZINE, cover_src)
st.iframe(magazine_html, height=IFRAME_HEIGHT)

if SHOW_PAGE_MAP:
    with st.expander("Page map (set SHOW_PAGE_MAP = False to hide)"):
        st.code(describe_pages(MAGAZINE), language=None)