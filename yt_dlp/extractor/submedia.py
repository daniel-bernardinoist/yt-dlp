import re

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
    clean_html,
    extract_attributes,
    get_element_by_class,
    get_elements_html_by_class,
    orderedSet,
    strip_or_none,
    unified_timestamp,
    url_or_none,
    urljoin,
)


class SubMediaBaseIE(InfoExtractor):
    _VALID_URL = False
    _SUBMEDIA_RE = r'https?://(?:www\.)?sub\.media/'

    _ENTRY_URL_PATTERNS = (
        r'<h2[^>]+class="[^"]*entry-title[^"]*"[^>]*>\s*<a[^>]+href="([^"]+)"',
        r'<h[23][^>]*>\s*<a[^>]+href="([^"]+)"',
        r'<a[^>]+class="[^"]*read-more[^"]*"[^>]+href="([^"]+)"',
    )

    def _extract_title(self, webpage):
        return (
            clean_html(get_element_by_class('entry-title', webpage))
            or self._html_search_regex(r'<h1[^>]*>([^<]+)', webpage, 'title', fatal=False)
            or self._html_extract_title(webpage)
        )

    def _extract_description(self, webpage):
        return (
            strip_or_none(clean_html(get_element_by_class('entry-content', webpage)))
            or strip_or_none(self._html_search_regex(
                r'<h5[^>]*>([^<]+)', webpage, 'description', fatal=False))
        )

    def _extract_uploader(self, webpage):
        return strip_or_none(clean_html(get_element_by_class('author-name', webpage)))

    def _extract_uploader_id(self, webpage):
        mobj = re.search(r'https?://(?:www\.)?sub\.media/author/([^/?#]+)/', webpage)
        return mobj.group(1) if mobj else None

    def _extract_timestamp(self, webpage):
        mobj = re.search(r'datetime="([^"]+)"', webpage)
        return unified_timestamp(mobj.group(1)) if mobj else None

    def _extract_thumbnail(self, webpage):
        mobj = re.search(
            r'<img[^>]+class="[^"]*wp-post-image[^"]*"[^>]+(?:data-src|src)="([^"]+)"',
            webpage)
        return mobj.group(1) if mobj else None

    def _extract_tags(self, webpage):
        tags = re.findall(r'<a[^>]+rel="tag"[^>]*>([^<]+)', webpage)
        return [clean_html(t) for t in tags] or None

    def _extract_categories(self, webpage):
        categories = re.findall(r'<a[^>]+rel="category tag"[^>]*>([^<]+)', webpage)
        categories += re.findall(r'<a[^>]+rel="category"[^>]*>([^<]+)', webpage)
        return [clean_html(c) for c in categories] or None

    def _build_metadata(self, webpage, display_id):
        return {
            'id': display_id,
            'display_id': display_id,
            'title': self._extract_title(webpage),
            'description': self._extract_description(webpage),
            'uploader': self._extract_uploader(webpage),
            'uploader_id': self._extract_uploader_id(webpage),
            'timestamp': self._extract_timestamp(webpage),
            'thumbnail': self._extract_thumbnail(webpage),
            'tags': self._extract_tags(webpage),
            'categories': self._extract_categories(webpage),
        }

    def _apply_metadata(self, info, metadata, overwrite_id=False):
        if not overwrite_id:
            metadata = {k: v for k, v in metadata.items() if k not in ('id',)}
        info.update({k: v for k, v in metadata.items() if v not in (None, [], '', {})})
        return info

    def _content_html(self, webpage):
        blocks = get_elements_html_by_class('entry-content', webpage)
        return '\n'.join(blocks) if blocks else webpage

    def _extract_post_urls(self, webpage, base_url):
        candidates = []
        content_html = self._content_html(webpage)
        for pattern in self._ENTRY_URL_PATTERNS:
            candidates.extend(re.findall(pattern, content_html))
        if not candidates:
            for pattern in self._ENTRY_URL_PATTERNS:
                candidates.extend(re.findall(pattern, webpage))

        urls = []
        for href in candidates:
            full_url = url_or_none(urljoin(base_url, href))
            if not full_url:
                continue
            if not re.match(self._SUBMEDIA_RE, full_url):
                continue
            if full_url.rstrip('/') == base_url.rstrip('/'):
                continue
            if '#pll_switcher' in full_url or '#content' in full_url:
                continue
            urls.append(full_url)
        return orderedSet(urls)

    def _next_page_url(self, webpage, base_url):
        next_url = self._search_regex(
            r'<a[^>]+class="[^"]*next[^"]*page-numbers[^"]*"[^>]+href="([^"]+)"',
            webpage, 'next page', fatal=False)
        if not next_url:
            next_url = self._search_regex(
                r'<a[^>]+rel="next"[^>]+href="([^"]+)"',
                webpage, 'next page', fatal=False)
        return urljoin(base_url, next_url) if next_url else None

    def _extract_post_entries(self, webpage, base_url):
        return [self.url_result(u, SubMediaIE) for u in self._extract_post_urls(webpage, base_url)]

    def _extract_iframe_urls(self, webpage, base_url):
        urls = []
        for iframe in re.findall(r'(?is)<iframe\b[^>]+>', webpage):
            attrs = extract_attributes(iframe)
            for key in ('src', 'data-src', 'data-lazy-src'):
                href = attrs.get(key)
                if href:
                    urls.append(urljoin(base_url, href))
                    break
        return orderedSet(url_or_none(u) for u in urls if url_or_none(u))

    def _paginate_entries(self, url, display_id, first_webpage=None, first_entries=None):
        page_url = url
        seen_pages = set()
        page_num = 1
        webpage = first_webpage
        entries = first_entries
        while page_url and page_url not in seen_pages:
            seen_pages.add(page_url)
            if webpage is None:
                webpage = self._download_webpage(
                    page_url, display_id, note=f'Downloading page {page_num}')
            if entries is None:
                entries = self._extract_post_entries(webpage, page_url)
            for entry in entries:
                yield entry
            page_url = self._next_page_url(webpage, page_url)
            webpage = None
            entries = None
            page_num += 1

    def _is_list_page(self, webpage):
        return bool(re.search(
            r'class="[^"]*page-numbers[^"]*"|\bRead\s+More\b', webpage))

    def _maybe_playlist_result(self, url, display_id, webpage, title=None, description=None, min_entries=3):
        if self._is_list_page(webpage):
            min_entries = min(min_entries, 2)
        first_entries = self._extract_post_entries(webpage, url)
        if len(first_entries) < min_entries:
            return None
        entries = self._paginate_entries(url, display_id, first_webpage=webpage, first_entries=first_entries)
        return self.playlist_result(entries, display_id, title=title, description=description)


class SubMediaListIE(SubMediaBaseIE):
    _VALID_URL = r'https?://(?:www\.)?sub\.media/(?:(?:author|c|tag|category)/(?P<id>[^/?#]+))(?:/page/(?P<page>\d+))?/?'
    _TESTS = [{
        'url': 'https://sub.media/author/sadmin/',
        'only_matching': True,
    }, {
        'url': 'https://sub.media/c/shorts/',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        display_id = self._match_id(url)
        webpage = self._download_webpage(url, display_id)
        entries = self._paginate_entries(
            url, display_id, first_webpage=webpage, first_entries=self._extract_post_entries(webpage, url))
        return self.playlist_result(
            entries, display_id, title=self._extract_title(webpage), description=self._extract_description(webpage))


class SubMediaPageIE(SubMediaBaseIE):
    _VALID_URL = r'https?://(?:www\.)?sub\.media/\?page_id=(?P<id>\d+)$'
    _TESTS = [{
        'url': 'https://sub.media/?page_id=72496',
        'only_matching': True,
    }, {
        'url': 'https://sub.media/?page_id=72567',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        page_id = self._match_id(url)
        webpage = self._download_webpage(url, page_id)

        entries = self._extract_post_entries(webpage, url)
        if entries:
            return self.playlist_result(
                self._paginate_entries(url, page_id, first_webpage=webpage, first_entries=entries),
                page_id, title=self._extract_title(webpage), description=self._extract_description(webpage))

        media_entries = self._parse_html5_media_entries(url, webpage, page_id, m3u8_id='hls') or []
        if media_entries:
            return self._apply_metadata(
                media_entries[0], self._build_metadata(webpage, page_id), overwrite_id=True)

        iframe_entries = [self.url_result(u) for u in self._extract_iframe_urls(self._content_html(webpage), url)]
        if iframe_entries:
            if len(iframe_entries) == 1:
                return self._apply_metadata(iframe_entries[0], self._build_metadata(webpage, page_id))
            return self.playlist_result(
                iframe_entries, page_id, title=self._extract_title(webpage))

        embeds = list(self._extract_generic_embeds(
            url, webpage, info_dict={'display_id': page_id}, note='Extracting embedded media'))
        if embeds:
            if len(embeds) == 1:
                return self._apply_metadata(embeds[0], self._build_metadata(webpage, page_id))
            return self.playlist_result(embeds, page_id, title=self._extract_title(webpage))

        raise ExtractorError('No media found', expected=True)


class SubMediaIE(SubMediaBaseIE):
    _VALID_URL = r'https?://(?:www\.)?sub\.media/(?P<id>[^/?#]+)/?'
    _TESTS = [{
        'url': 'https://sub.media/burning-cop-car-16/',
        'info_dict': {
            'id': 'burning-cop-car-16',
            'display_id': 'burning-cop-car-16',
            'ext': 'mp3',
            'title': 'Burning Cop Car #16',
        },
        'params': {'skip_download': True},
    }, {
        'url': 'https://sub.media/what-is-property/',
        'only_matching': True,
    }, {
        'url': 'https://sub.media/videos-2/',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        display_id = self._match_id(url)
        webpage = self._download_webpage(url, display_id)
        metadata = self._build_metadata(webpage, display_id)

        media_entries = self._parse_html5_media_entries(url, webpage, display_id, m3u8_id='hls') or []
        if media_entries:
            return self._apply_metadata(media_entries[0], metadata, overwrite_id=True)

        iframe_entries = [self.url_result(u) for u in self._extract_iframe_urls(self._content_html(webpage), url)]
        if iframe_entries:
            if len(iframe_entries) == 1:
                return self._apply_metadata(iframe_entries[0], metadata)
            return self.playlist_result(iframe_entries, display_id, title=metadata.get('title'))

        embeds = list(self._extract_generic_embeds(
            url, webpage, info_dict={'display_id': display_id}, note='Extracting embedded media'))
        if embeds:
            if len(embeds) == 1:
                return self._apply_metadata(embeds[0], metadata)
            return self.playlist_result(embeds, display_id, title=metadata.get('title'))

        playlist = self._maybe_playlist_result(
            url, display_id, webpage, title=metadata.get('title'), description=metadata.get('description'))
        if playlist:
            return playlist

        raise ExtractorError('No media found', expected=True)
