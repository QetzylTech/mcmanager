"""Thin API handlers for the 17 presentation page modules."""

from __future__ import annotations

from flask import Blueprint, current_app

from app.shell.routes import PAGE_BY_SLUG, PAGE_MODULES
from app.web.errors import error, ok

pages_bp = Blueprint('api_pages', __name__, url_prefix='/api/pages')


@pages_bp.get('')
def list_pages():
    return ok(
        {
            'pages': [
                {'slug': page.slug, 'title': page.title, 'scope': page.scope, 'api_path': page.api_path}
                for page in PAGE_MODULES
            ]
        }
    )


@pages_bp.get('/<slug>')
def page_module(slug: str):
    page = PAGE_BY_SLUG.get(slug)
    if page is None:
        return error('NOT_FOUND', 'Page module not found.', status=404)
    container = current_app.extensions['mcmanager_container']
    try:
        worlds = container.worlds.list_worlds()
        running = [w for w in worlds if w['state'] == 'running']
        sections = _sections_for(page.slug)
        payload = {
            'slug': page.slug,
            'title': page.title,
            'scope': page.scope,
            'sections': sections,
        }
        if page.slug == 'worlds':
            payload['worlds'] = worlds
        elif page.slug == 'home':
            payload['running_worlds'] = running
            payload['recent_worlds'] = worlds[:5]
        elif page.slug == 'world-main':
            payload['worlds'] = worlds
        return ok(payload)
    except Exception:
        return error('PAGE_UNAVAILABLE', 'Page module failed to load.', status=500)


def _sections_for(slug: str) -> list[dict[str, str]]:
    sections = {
        'home': [('Server Stats', 'CPU, RAM, storage, and world status snapshot.'), ('Running Worlds', 'Quick action surface for active worlds.'), ('Recent Worlds', 'The five most recently used worlds.')],
        'worlds': [('World List', 'Search and filter managed worlds.'), ('Create World', 'Template-driven world creation.'), ('Schedules', 'Global backup schedules and triggers.')],
        'settings': [('Global Settings', 'Timezone, idle countdown, notification defaults, and paths.')],
        'users': [('Users', 'Accounts, roles, permissions, and device access.')],
        'maintenance': [('Retention Policies', 'Global cleanup rules, dry runs, and missed jobs.')],
        'documentation': [('Documentation', 'Rendered administration and developer manuals.')],
        'system-logs': [('Manager Logs', 'Panel activity, errors, and notifications.')],
        'audit': [('Audit History', 'Immutable actions, denials, restores, cleanup, and crashes.')],
        'sync': [('Sync Targets', 'Global and per-world offsite sync configuration.'), ('Recent Sync Activity', 'Sync records and attempt outcomes.')],
        'manager-maintenance': [('Manager Actions', 'Manager backup, restore, restart, update, and rollback.')],
        'templates': [('Templates', 'Template catalog, versions, server type, and Java runtime defaults.')],
        'world-main': [('World Stats', 'Selected-world state, size, players, port, and backups.'), ('Controls', 'Start, stop, and backup actions.')],
        'world-backups': [('Backups', 'Artifacts, integrity, restore actions, and sync status.')],
        'world-logs': [('Live Logs', 'Minecraft, debug, crash, backup, and restore streams.')],
        'files': [('File Browser', 'Guarded upload, delete, rename, move, copy, and folder creation.')],
        'world-maintenance': [('World Retention', 'Per-world overrides and cleanup previews.')],
        'world-setup': [('Server Properties', 'Version-aware guarded configuration editor.')],
    }
    return [{'title': title, 'summary': summary} for title, summary in sections[slug]]
