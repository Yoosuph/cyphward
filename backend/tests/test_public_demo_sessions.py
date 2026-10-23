"""Public owner-account demos stay scoped across reads, writes and refresh.

Uses the real JWT/session/auth chain with the isolated SQL fixture. No live
accounts, provider calls, messages or production credentials are used.
"""
from datetime import datetime, timezone
from uuid import uuid4

import jwt
import pytest
from starlette.requests import Request

from backend.app.api import demo_login
from backend.app.core.auth import get_current_user
from backend.app.core.sessions import issue_session
from conftest import ALICE, ORG_A, ORG_B


@pytest.fixture
def configured_demo(store, monkeypatch):
    profile = store.profiles[ALICE]
    profile['email_verified_at'] = datetime.now(timezone.utc)
    for key, value in {'DEMO_LOGIN_ENABLED':'true', 'DEMO_LOGIN_USER_ID':ALICE,
                       'DEMO_LOGIN_ORG_ID':ORG_A, 'DEMO_LOGIN_EMAIL':profile['email']}.items():
        monkeypatch.setenv(key, value)
    # Teach only the two demo-admission queries to the existing SQL fixture.
    one, query = demo_login.execute_one, demo_login.execute_query
    def demo_one(sql, params=()):
        if sql == 'SELECT * FROM profiles WHERE id = %s AND email = %s':
            user = store.profiles.get(str(params[0]))
            return user if user and user['email'] == params[1] else None
        return one(sql, params)
    def demo_query(sql, params=()):
        if sql == 'SELECT org_id, role FROM organization_members WHERE user_id = %s':
            return [dict(m) for m in store.memberships if m['user_id'] == params[0]]
        return query(sql, params)
    monkeypatch.setattr(demo_login, 'execute_one', demo_one)
    monkeypatch.setattr(demo_login, 'execute_query', demo_query)
    return profile


def enter(client):
    result = client.post('/api/v1/auth/demo-login')
    assert result.status_code == 200, result.text
    return result.json()


def headers(tokens, org=None):
    result = {'Authorization': 'Bearer ' + tokens['access_token']}
    if org:
        result['X-Organization-Id'] = org
    return result


def test_owner_demo_needs_no_password_or_challenge_but_has_only_member_access(client, configured_demo):
    tokens = enter(client)
    assert 'mfa_required' not in tokens
    assert tokens['user']['demo_session'] is True
    assert client.get('/api/v1/auth/bootstrap', headers=headers(tokens)).json()['memberships'][0]['role'] == 'member'
    current = client.get('/api/v1/organizations/current', headers=headers(tokens)).json()
    assert current['id'] == ORG_A and current['role'] == 'member'
    assert client.get('/api/v1/organizations/export', headers=headers(tokens)).status_code == 403


def test_normal_owner_session_and_ownership_are_unchanged(client, configured_demo, store):
    enter(client)
    tokens = issue_session(configured_demo)
    assert 'demo_session' not in tokens['user']
    current = client.get('/api/v1/organizations/current', headers=headers(tokens)).json()
    assert current['role'] == 'owner'
    assert next(m for m in store.memberships if m['user_id'] == ALICE)['role'] == 'owner'


def test_new_membership_does_not_expand_an_existing_demo_session(client, configured_demo, store):
    tokens = enter(client)
    store.memberships.append({'user_id':ALICE, 'org_id':ORG_B, 'role':'owner'})
    assert client.get('/api/v1/organizations/current', headers=headers(tokens, ORG_B)).status_code == 403
    assert [m['org']['id'] for m in client.get('/api/v1/auth/bootstrap', headers=headers(tokens)).json()['memberships']] == [ORG_A]
    listing = client.get('/api/v1/organizations', headers=headers(tokens)).json()
    assert [(o['id'], o['role']) for o in listing] == [(ORG_A, 'member')]
    assert client.post('/api/v1/auth/demo-login').status_code == 404


@pytest.mark.parametrize('path', ['/api/v1/domains', '/api/v1/organizations', '/api/v1/reports',
                                '/api/v1/auth/mfa/enroll', '/api/v1/auth/totp/enroll/start',
                                '/api/v1/auth/account/delete', '/api/v1/members/invites/accept'])
def test_public_demo_cannot_write_even_without_an_org_role_gate(client, configured_demo, path):
    tokens = enter(client)
    result = client.post(path, json={}, headers=headers(tokens))
    assert result.status_code == 403, result.text
    assert 'view-only' in result.json()['detail']


def test_staff_grants_never_work_in_public_demo_sessions(client, configured_demo, store):
    store.staff_grants.append({'id':str(uuid4()), 'user_id':ALICE, 'scopes':['platform:read'],
                               'created_at':datetime.now(timezone.utc), 'expires_at':None, 'revoked_at':None})
    tokens = enter(client)
    assert client.get('/api/v1/platform/health', headers=headers(tokens)).status_code == 403
    assert client.get('/api/v1/owner/overview', headers=headers(tokens)).status_code in (401, 403)


def test_refresh_rotation_preserves_scope_and_cannot_be_stripped_or_replayed(client, configured_demo):
    tokens = enter(client)
    first_refresh = tokens['refresh_token']
    for _ in range(2):
        forged = tokens['refresh_token'].split(':')[-1]
        assert client.post('/api/v1/auth/refresh', json={'refresh_token':forged}).status_code == 401
        result = client.post('/api/v1/auth/refresh', json={'refresh_token':tokens['refresh_token']})
        assert result.status_code == 200
        tokens = result.json()
        claims = jwt.decode(tokens['access_token'], options={'verify_signature':False})
        assert claims['demo_org_id'] == ORG_A
        assert client.get('/api/v1/organizations/export', headers=headers(tokens)).status_code == 403
    assert client.post('/api/v1/auth/refresh', json={'refresh_token':first_refresh}).status_code == 401


def test_invalid_target_and_disabling_demo_fail_closed(client, configured_demo, monkeypatch):
    tokens = enter(client)
    monkeypatch.setenv('DEMO_LOGIN_ENABLED', 'false')
    assert client.get('/api/v1/auth/bootstrap', headers=headers(tokens)).status_code == 401
    assert client.post('/api/v1/auth/refresh', json={'refresh_token':tokens['refresh_token']}).status_code == 401
    monkeypatch.setenv('DEMO_LOGIN_ENABLED', 'true')
    monkeypatch.delenv('DEMO_LOGIN_ORG_ID')
    assert client.get('/api/v1/auth/demo-login').json() == {'enabled':False}
    assert client.post('/api/v1/auth/demo-login').status_code == 404


def test_account_security_changes_end_public_access(client, configured_demo):
    tokens = enter(client)
    configured_demo['mfa_enrolled_at'] = datetime.now(timezone.utc)
    assert client.post('/api/v1/auth/demo-login').status_code == 404
    assert client.get('/api/v1/auth/bootstrap', headers=headers(tokens)).status_code == 401


def test_platform_owners_are_never_public_demo_targets(client, configured_demo, store):
    store.platform_owners[ALICE] = {'user_id':ALICE, 'console_only':False}
    assert client.post('/api/v1/auth/demo-login').status_code == 404


def test_demo_logout_does_not_end_the_private_owners_session(client, configured_demo):
    demo = enter(client)
    private = issue_session(configured_demo)
    assert client.post('/api/v1/auth/logout', json={'refresh_token':demo['refresh_token']}).status_code == 200
    assert client.get('/api/v1/organizations/current', headers=headers(demo)).status_code == 401
    assert client.get('/api/v1/organizations/current', headers=headers(private)).json()['role'] == 'owner'


def test_evidence_interpretation_remains_available_without_a_model_call(client, configured_demo):
    tokens = enter(client)
    request = Request({'type':'http', 'method':'POST', 'path':'/api/v1/ai/chat/stream',
                       'scheme':'http', 'server':('testserver',80), 'headers':[]})
    user = get_current_user(authorization=headers(tokens)['Authorization'], request=request)
    assert user['session_demo_org_id'] == ORG_A
