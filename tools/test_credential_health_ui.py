"""Headless UI regression. Every /api request is intercepted; no real key/account/API call."""
import datetime
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/credential-health-20261114'


def main():
    now=int(time.time()*1000)
    state={'status':'EXPIRED','level':'error','message':'Bybit API 密钥已过期，请更新凭证','environment':'DEMO',
           'checkedAt':now,'retCode':33004,'httpStatus':200,'stale':False,'expiresAt':None}
    calls=[];violations=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        def route(request_route):
            request=request_route.request;url=request.url;method=request.method
            calls.append({'path':url.split('/api/',1)[1],'method':method})
            if method!='GET' and '/validate' not in url:
                violations.append(url);request_route.fulfill(status=403,json={'error':'unexpected mutation'});return
            if '/api/bybit/mode' in url:data={'mode':'DEMO'}
            elif '/api/credentials/1/health' in url or '/api/credentials/1/validate' in url:data=state.copy()
            elif '/api/credentials' in url:data=[{'id':1,'name':'demo-ui-fixture','maskedApiKey':'demo********test','createdAt':'2026-11-01T00:00:00','updatedAt':'2026-11-01T00:00:00'}]
            elif '/wallet-balance' in url:data={'retCode':33004,'retMsg':'expired'}
            elif 'instruments-info' in url:data={'retCode':0,'result':{'list':[]}}
            else:data={'retCode':0,'result':{'list':[]}}
            request_route.fulfill(status=200,json=data)
        page.route('**/api/**',route)
        # Never permit accidental third-party browser network traffic.
        page.route('https://**/*',lambda r:r.abort())
        page.goto('http://127.0.0.1:4183/credentials')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_test_id('credential-health-1').first).to_contain_text('密钥已过期')
        assert 'fake-secret' not in page.inner_text('body')
        page.screenshot(path=str(OUT/'ui-expired.png'),full_page=True)
        state.update(status='EXPIRING',level='warning',message='密钥即将到期，请按精确到期时间提前更新；实际交易未验证',
                     retCode=0,remainingDays=0,expiresAt=datetime.datetime.fromtimestamp((now+12*3600000)/1000,datetime.timezone.utc).isoformat())
        page.get_by_test_id('credential-health-1').first.get_by_role('button',name='重新检测').click()
        expect(page.get_by_test_id('credential-health-1').first).to_contain_text('密钥即将到期')
        expect(page.get_by_test_id('credential-health-1').first).to_contain_text('是否到期以精确时间为准')
        page.screenshot(path=str(OUT/'ui-expiring.png'),full_page=True)
        state.update(status='NETWORK_ERROR',level='warning',message='未能连接 Bybit，无法判断密钥是否有效',retCode=None,expiresAt=None,remainingDays=None)
        page.get_by_test_id('credential-health-1').first.get_by_role('button',name='重新检测').click()
        expect(page.get_by_test_id('credential-health-1').first).to_contain_text('无法判断密钥是否有效')
        state.update(status='READ_ONLY_OK',message='只读鉴权成功；到期时间和交易能力尚未完整确认',retCode=0)
        page.get_by_test_id('credential-health-1').first.get_by_role('button',name='重新检测').click()
        expect(page.get_by_test_id('credential-health-1').first).to_contain_text('到期时间和交易能力尚未完整确认')
        state.update(status='VALID',level='success',message='鉴权成功且到期时间未到；实际下单能力未验证',
                     expiresAt=datetime.datetime.fromtimestamp((now+30*86400000)/1000,datetime.timezone.utc).isoformat(),remainingDays=30)
        page.get_by_test_id('credential-health-1').first.get_by_role('button',name='重新检测').click()
        expect(page.get_by_test_id('credential-health-1').first).to_contain_text('鉴权成功且到期时间未到')
        expect(page.get_by_test_id('credential-health-1').first).not_to_contain_text('密钥已过期')
        page.screenshot(path=str(OUT/'ui-renewed.png'),full_page=True)
        page.goto('http://127.0.0.1:4183/trade')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_text('余额暂不可用，未按零余额处理。请到凭证管理检查密钥及环境。')).to_be_visible()
        page.screenshot(path=str(OUT/'ui-wallet-error.png'),full_page=True)
        assert not violations,violations
        result={'expired_visible':True,'zero_days_future_expiry_warns':True,'network_not_expired':True,
                'read_only_not_trade_certification':True,'failed_wallet_not_zero':True,
                'renewal_recovers':True,
                'unexpected_mutations':len(violations),'api_intercepted':True,'real_accounts_used':False,'calls':calls}
        (OUT/'ui-tests.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        browser.close()
        print(json.dumps({k:v for k,v in result.items() if k!='calls'},indent=2))


if __name__=='__main__':main()
