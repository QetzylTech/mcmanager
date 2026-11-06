"""Persistent web shell routes."""

from __future__ import annotations

from dataclasses import dataclass

from flask import Blueprint, abort, render_template


@dataclass(frozen=True)
class PageModule:
    slug: str
    title: str
    scope: str
    api_path: str


PAGE_MODULES = (
    PageModule('home', 'Homepage', 'manager', '/api/pages/home'),
    PageModule('worlds', 'World Management', 'manager', '/api/pages/worlds'),
    PageModule('settings', 'Manager Settings', 'manager', '/api/pages/settings'),
    PageModule('users', 'User Management', 'manager', '/api/pages/users'),
    PageModule('maintenance', 'Maintenance & Retention', 'manager', '/api/pages/maintenance'),
    PageModule('documentation', 'Instructions & Documentation', 'manager', '/api/pages/documentation'),
    PageModule('system-logs', 'System Logs', 'manager', '/api/pages/system-logs'),
    PageModule('audit', 'Audit/History', 'manager', '/api/pages/audit'),
    PageModule('sync', 'Offsite Sync Settings', 'manager', '/api/pages/sync'),
    PageModule('manager-maintenance', 'Manager Maintenance', 'manager', '/api/pages/manager-maintenance'),
    PageModule('templates', 'World Template Catalog', 'manager', '/api/pages/templates'),
    PageModule('world-main', 'World Main', 'world', '/api/pages/world-main'),
    PageModule('world-backups', 'World Backup & Restore', 'world', '/api/pages/world-backups'),
    PageModule('world-logs', 'World Logs', 'world', '/api/pages/world-logs'),
    PageModule('files', 'File Manager', 'world', '/api/pages/files'),
    PageModule('world-maintenance', 'World Maintenance & Retention', 'world', '/api/pages/world-maintenance'),
    PageModule('world-setup', 'World Setup', 'world', '/api/pages/world-setup'),
)

PAGE_BY_SLUG = {page.slug: page for page in PAGE_MODULES}

shell_bp = Blueprint('shell', __name__)


@shell_bp.get('/')
def index():
    return render_template('shell.html', pages=PAGE_MODULES, active='home')


@shell_bp.get('/pages/<slug>')
def page(slug: str):
    if slug not in PAGE_BY_SLUG:
        abort(404)
    return render_template('shell.html', pages=PAGE_MODULES, active=slug)
