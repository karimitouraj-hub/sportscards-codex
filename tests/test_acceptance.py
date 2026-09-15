"""Synthetic fixtures only. Never use the production collection directory."""
import datetime as dt
import hashlib
import io
import json
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image, ImageDraw
import pillow_heif

from server.app import create_app, process_one, recover
from server.valuation import value_card


def fixture_image(fmt='PNG', color='#263d33', boxes=True):
    image = Image.new('RGB', (1000, 700), color)
    if boxes:
        draw = ImageDraw.Draw(image)
        for x in (90, 540):
            draw.rectangle((x, 80, x+290, 510), fill='white', outline='#dddddd', width=4)
            draw.text((x+30, 130), 'SYNTHETIC TEST CARD', fill='black')
            draw.text((x+30, 200), 'Test Player / 2024 / #12', fill='black')
    out = io.BytesIO()
    image.save(out, fmt)
    return out.getvalue()


@pytest.fixture
def app(tmp_path):
    assert '/data/sportscards/' not in str(tmp_path)
    return create_app(tmp_path)


@pytest.fixture
def client(app):
    client = app.test_client()
    token = client.get('/api/state').json['token']
    client.environ_base['HTTP_X_SPORTSCARDS_TOKEN'] = token
    return client


def upload(client, content=None):
    return client.post('/api/photos', data=content or fixture_image(), headers={'X-Filename':'synthetic.png','Content-Type':'application/octet-stream'})


def observations(app, client):
    result = upload(client)
    assert result.status_code == 201, result.json
    assert process_one(app.store)
    return client.get('/api/state').json['observations']


IDENTITY = dict(player='Test Player', year='2024', set='Test Set', number='12', variant='Base', grade='Raw', condition='Near mint')


def card(client, observation, **changes):
    result = client.post('/api/cards', json={**IDENTITY, **changes, 'observation_id':observation['id'], 'side':'front'})
    assert result.status_code == 201, result.json
    return result.json


def purchase(client, **changes):
    result = client.post('/api/purchases', json=dict(title='2024 Test Player Test Set 12 two-card lot', source_ref='TEST-ORDER-1',
                        account='Synthetic account', quantity=2, total_cents=1000, refund_cents=200, **changes))
    assert result.status_code == 201, result.json
    return result.json


@pytest.mark.parametrize('fmt', ['JPEG','PNG','WEBP','HEIF'])
def test_decoding_original_and_duplicate(app, client, fmt):
    pillow_heif.register_heif_opener()
    data = fixture_image(fmt)
    response = upload(client,data)
    assert response.status_code == 201, response.json
    photo=response.json['photo']
    assert photo['format'] == fmt
    assert client.get('/media/original/'+photo['id']).data == data
    assert hashlib.sha256(data).hexdigest() == photo['sha256']
    assert client.get('/media/preview/'+photo['id']).status_code == 200
    assert upload(client,data).json['status'] == 'duplicate'
    assert len(client.get('/api/state').json['photos']) == 1


@pytest.mark.parametrize('data', [b'not an image', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', b'\xff\xd8\xffbad'])
def test_bad_content_leaves_no_records(app, client, data):
    assert upload(client,data).status_code == 422
    assert client.get('/api/state').json['photos'] == []
    assert list((app.store.root/'staging').iterdir()) == []


@pytest.mark.parametrize('fmt', ['WEBP', 'PNG'])
def test_animation_rejected(client, fmt):
    data=io.BytesIO()
    Image.new('RGB',(80,80),'red').save(data,fmt,save_all=True,append_images=[Image.new('RGB',(80,80),'blue')],duration=200,loop=0)
    with Image.open(io.BytesIO(data.getvalue())) as animated:
        assert animated.is_animated and animated.n_frames == 2
        assert animated.size == (80, 80)  # Valid dimensions isolate the animation check.
    assert upload(client,data.getvalue()).status_code == 422


def fixture_heif_collection(primary_size=(80,120)):
    pillow_heif.register_heif_opener()
    other = Image.new('RGB', (64,96), 'red')
    primary = Image.new('RGB', primary_size, 'green')
    primary.paste('blue', (primary.width//2, 0, primary.width, primary.height))
    exif = primary.getexif()
    exif[274] = 6
    primary.info['exif'] = exif.tobytes()
    output = io.BytesIO()
    other.save(output, 'HEIF', append_images=[primary], save_all=True, primary_index=1, quality=100)
    return output.getvalue()


def test_multi_image_heif_uses_declared_primary_for_preview_and_crop(app, client):
    data = fixture_heif_collection()
    with Image.open(io.BytesIO(data)) as source:
        assert source.format == 'HEIF'
        assert source.n_frames == 2 and source.is_animated
        assert source.tell() == 1 and source.info['primary'] is True
        assert source.custom_mimetype == 'image/heic'
        assert source.size == (120, 80)
    response = upload(client, data)
    assert response.status_code == 201, response.json
    photo = response.json['photo']
    assert (photo['width'], photo['height']) == (120, 80)
    assert client.get('/media/original/'+photo['id']).data == data
    assert photo['sha256'] == hashlib.sha256(data).hexdigest()
    with Image.open(io.BytesIO(client.get('/media/preview/'+photo['id']).data)) as preview:
        assert preview.size == (120, 80)
        green, blue = preview.getpixel((60,20)), preview.getpixel((60,60))
        assert green[1] > green[0]+70 and green[1] > green[2]+70
        assert blue[2] > blue[0]+150 and blue[2] > blue[1]+150
    assert process_one(app.store)
    assert client.get('/api/state').json['jobs'][0]['state'] == 'done'
    crop = client.post('/api/observations', json={'photo_id': photo['id'], 'bbox': [0,0,1,.5]})
    assert crop.status_code == 201, crop.json
    with Image.open(io.BytesIO(client.get('/media/crop/'+crop.json['id']).data)) as image:
        assert image.size == (120,40)
        pixel = image.getpixel((60,20))
        assert pixel[1] > pixel[0]+70 and pixel[1] > pixel[2]+70
    assert upload(client, data).json['status'] == 'duplicate'
    assert len(app.store.all('photo')) == 1


@pytest.mark.parametrize('brand', [b'hevc', b'msf1'])
def test_declared_heif_sequences_remain_rejected(client, brand):
    data = fixture_heif_collection()
    # Keep a real encoded container but declare a sequence major brand.
    sequence = data[:8]+brand+data[12:]
    with Image.open(io.BytesIO(sequence)) as image:
        assert image.format == 'HEIF'
        assert image.custom_mimetype.endswith('-sequence')
    assert upload(client, sequence).status_code == 422


def test_multi_image_heif_checks_primary_dimensions(client):
    assert upload(client, fixture_heif_collection(primary_size=(24,24))).status_code == 422


def test_multi_image_jpeg_uses_primary_for_preview_and_crop(app, client):
    primary = Image.new('RGB', (80, 120), 'green')
    primary.paste('blue', (40, 0, 80, 120))
    exif = primary.getexif()
    exif[274] = 6
    output = io.BytesIO()
    primary.save(output, 'MPO', save_all=True, append_images=[Image.new('RGB', (40, 60), 'red')],
                 exif=exif, quality=100)
    data = output.getvalue()
    with Image.open(io.BytesIO(data)) as source:
        assert source.format == 'MPO'
        assert source.is_animated and source.n_frames == 2
        assert source.tell() == 0 and source.getexif()[274] == 6
        assert source.mpinfo[0xB002][0]['Attribute']['MPType'] == 'Baseline MP Primary Image'
    response = upload(client, data)
    assert response.status_code == 201, response.json
    photo = response.json['photo']
    assert photo['format'] == 'JPEG' and photo['container_format'] == 'MPO'
    assert photo['primary_image_index'] == 0
    assert (photo['width'], photo['height']) == (120, 80)
    original = client.get('/media/original/'+photo['id'])
    assert original.data == data and photo['sha256'] == hashlib.sha256(data).hexdigest()
    assert '.jpeg' in original.headers['Content-Disposition']
    with Image.open(io.BytesIO(client.get('/media/preview/'+photo['id']).data)) as preview:
        assert preview.size == (120, 80)
        green, blue = preview.getpixel((60,20)), preview.getpixel((60,60))
        assert green[1] > green[0]+70 and green[1] > green[2]+70
        assert blue[2] > blue[0]+150 and blue[2] > blue[1]+150
    assert process_one(app.store)
    assert client.get('/api/state').json['jobs'][0]['state'] == 'done'
    crop = client.post('/api/observations', json={'photo_id': photo['id'], 'bbox': [0,0,1,.5]})
    assert crop.status_code == 201, crop.json
    with Image.open(io.BytesIO(client.get('/media/crop/'+crop.json['id']).data)) as image:
        assert image.size == (120,40)
        pixel = image.getpixel((60,20))
        assert pixel[1] > pixel[0]+70 and pixel[1] > pixel[2]+70
    assert upload(client, data).json['status'] == 'duplicate'
    assert len(app.store.all('photo')) == 1


def test_exif_orientation(client):
    data=io.BytesIO()
    im=Image.new('RGB',(80,120),'blue')
    exif=im.getexif();exif[274]=6
    im.save(data,'JPEG',exif=exif)
    photo=upload(client,data.getvalue()).json['photo']
    assert (photo['width'],photo['height']) == (120,80)


def test_multi_card_detection_and_manual_crop(app,client):
    obs=observations(app,client)
    assert len(obs)==2
    for item in obs:
        assert item['card_id'] is None
        assert item['identity_proposal']['status']=='unresolved'
        assert client.get('/media/crop/'+item['id']).status_code==200
    result=client.post('/api/observations',json={'photo_id':obs[0]['photo_id'],'bbox':[0,.8,.2,.2]})
    assert result.status_code==201
    assert result.json['method']=='manual'


@pytest.mark.parametrize('box', [[-1,0,.1,.1],[0,0,2,1],[0,0,0,0],['a',0,1,1],[0,0,float('nan'),1]])
def test_invalid_crop(app,client,box):
    obs=observations(app,client)
    assert client.patch('/api/observations/'+obs[0]['id'],json={'bbox':box}).status_code==400


def test_physical_copies_and_front_back_link(app,client):
    obs=observations(app,client)
    first=card(client,obs[0]);second=card(client,obs[1])
    assert first['id']!=second['id']
    assert len(client.get('/api/state').json['cards'])==2
    extra=client.post('/api/observations',json={'photo_id':obs[0]['photo_id'],'bbox':[0,0,.05,.05]}).json
    assert client.post('/api/cards/'+first['id']+'/link',json={'observation_id':extra['id'],'side':'back'}).status_code==200
    assert len(client.get('/api/state').json['cards'])==2
    assert client.post('/api/cards/'+second['id']+'/link',json={'observation_id':extra['id'],'side':'back'}).status_code==409
    assert client.post('/api/cards',json={**IDENTITY,'observation_id':obs[0]['id']}).status_code==409


def test_review_completion_and_optimistic_correction(app,client):
    obs=observations(app,client)
    pid=obs[0]['photo_id']
    assert client.post('/api/photos/'+pid+'/review',json={}).status_code==409
    c=card(client,obs[0])
    client.patch('/api/observations/'+obs[1]['id'],json={'status':'ignored'})
    assert client.post('/api/photos/'+pid+'/review',json={}).json['review_complete']
    assert client.patch('/api/cards/'+c['id'],json={'revision':1,'player':'Corrected Player'}).json['revision']==2
    assert client.patch('/api/cards/'+c['id'],json={'revision':1,'player':'Stale'}).status_code==409


def test_queue_survives_restart(app,client):
    pid=upload(client).json['photo']['id']
    with app.store.connect() as db:
        db.execute("UPDATE jobs SET state='processing' WHERE photo_id=?",(pid,))
    reloaded=create_app(app.store.root)
    recover(reloaded.store)
    assert process_one(reloaded.store)
    assert not process_one(reloaded.store)
    assert len(reloaded.store.all('observation'))==2
    assert reloaded.store.all('photo')[0]['sha256']


def test_failed_job_retry(app,client,monkeypatch):
    pid=upload(client).json['photo']['id']
    import server.app as module
    real=module.detect
    monkeypatch.setattr(module,'detect',lambda p: (_ for _ in ()).throw(ValueError()))
    process_one(app.store)
    assert client.get('/api/state').json['jobs'][0]['state']=='failed'
    monkeypatch.setattr(module,'detect',real)
    assert client.post('/api/photos/'+pid+'/retry',json={}).status_code==200
    process_one(app.store)
    assert len(app.store.all('observation'))==2


def test_purchase_allocation_refund_quantity_and_cancellation(app,client):
    obs=observations(app,client)
    first=card(client,obs[0]);second=card(client,obs[1]);line=purchase(client)
    def alloc(c,cost):return client.post('/api/cards/'+c['id']+'/allocation',json={'purchase_id':line['id'],'cost_cents':cost,'basis':'Equal share after refund'})
    assert alloc(first,500).status_code==200
    assert alloc(second,500).status_code==409
    assert alloc(first,400).status_code==200
    assert alloc(second,400).status_code==200
    assert len(client.get('/api/state').json['allocations'])==2
    assert client.get('/api/cards/'+first['id']+'/analysis').json['purchases'][0]['status']=='suggested'
    cancelled=client.post('/api/purchases',json={'title':'cancelled','source_ref':'CANCELLED','quantity':1,'total_cents':50,'status':'cancelled'}).json
    assert client.post('/api/cards/'+first['id']+'/allocation',json={'purchase_id':cancelled['id'],'cost_cents':0,'basis':'none'}).status_code==400


def test_valuation_filtering_and_net_proceeds():
    today=dt.date(2026,9,14)
    comps=[dict(id=str(i),**IDENTITY,source_url=f'https://example.com/{i}',status='sold',currency='USD',sold_date='2026-09-01',price_cents=price,shipping_cents=100) for i,price in enumerate([900,1100,1300])]
    comps += [dict(comps[0],id='asking',status='asking'),dict(comps[0],id='variant',variant='Gold'),dict(comps[0],id='stale',sold_date='2025-01-01'),dict(comps[0],id='duplicate')]
    value=value_card(IDENTITY,comps,{'percent':10,'fixed_cents':30,'shipping_cents':100},400,today)
    assert value['market_value_cents']==1200
    assert value['net_proceeds_cents']==950
    assert value['profit_cents']==550
    assert len(value['excluded'])==4
    assert value_card(dict(IDENTITY,grade=''),comps,today=today)['market_value_cents'] is None
    assert value_card(IDENTITY,comps[:2],today=today)['market_value_cents'] is None


def test_exports_and_formula_neutralization(app,client):
    obs=observations(app,client)
    card(client,obs[0],player='=HYPERLINK("https://example.com")')
    exported=client.get('/api/export/json')
    assert exported.json['schema_version']==2
    assert len(exported.json['observations'])==2
    assert exported.json['audit']
    csv=client.get('/api/export/csv')
    assert "'=HYPERLINK" in csv.text
    assert 'attachment' in csv.headers['Content-Disposition']


def test_host_origin_csrf_and_paths(app,client):
    assert app.test_client().post('/api/purchases',json={}).status_code==403
    assert client.post('/api/purchases',json={},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/state',headers={'Host':'evil.example'}).status_code==403
    assert client.get('/media/original/../../session-token').status_code==404
    response=client.get('/api/state')
    assert response.headers['Cache-Control']=='no-store'
    assert response.headers['X-Content-Type-Options']=='nosniff'


def test_twenty_additional_photos_after_five_originals(app,client):
    limits = client.get('/api/health').json['limits']
    assert limits['photos_per_batch'] == 20
    assert 'photos' not in limits
    images = [fixture_image(color=f'#{index:06x}', boxes=False) for index in range(1, 26)]
    saved = []
    for content in images[:5]:
        response = upload(client, content)
        assert response.status_code == 201, response.json
        saved.append(response.json['photo'])
    for content in images[5:]:
        response = upload(client, content)
        assert response.status_code == 201, response.json
        saved.append(response.json['photo'])
    state = client.get('/api/state').json
    assert len(state['photos']) == len(state['jobs']) == 25
    assert len({photo['sha256'] for photo in state['photos']}) == 25
    assert all(job['state'] == 'queued' for job in state['jobs'])
    for content, photo in zip(images, saved):
        assert client.get('/media/original/'+photo['id']).data == content
    for index in (0, 24):
        response = upload(client, images[index])
        assert response.status_code == 200
        assert response.json['status'] == 'duplicate'
        assert response.json['photo']['id'] == saved[index]['id']
    assert upload(client, b'not a supported photo').status_code == 422
    final = client.get('/api/state').json
    assert len(final['photos']) == len(final['jobs']) == 25
    assert list((app.store.root/'staging').iterdir()) == []


def test_concurrent_duplicate_is_one_photo(app,client):
    token=client.get('/api/state').json['token']
    data=fixture_image()
    def send(_):
        c=app.test_client();c.environ_base['HTTP_X_SPORTSCARDS_TOKEN']=token
        return upload(c,data).json['status']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(send,range(2)))==['duplicate','saved']
    assert len(app.store.all('photo'))==1


def test_comparable_api_recomputes_after_correction(app,client):
    c=card(client,observations(app,client)[0])
    for i in range(3):
        result=client.post('/api/cards/'+c['id']+'/comparables',json={**IDENTITY,'source_url':f'https://example.com/test/{i}','sold_date':dt.date.today().isoformat(),'status':'sold','price_cents':1000+i*100})
        assert result.status_code==201,result.json
    assert client.get('/api/cards/'+c['id']+'/analysis').json['valuation']['market_value_cents']==1100
    client.patch('/api/cards/'+c['id'],json={'revision':1,'variant':'Gold'})
    assert client.get('/api/cards/'+c['id']+'/analysis').json['valuation']['market_value_cents'] is None


def test_ocr_evidence_and_crop_invalidation(app,client):
    obs=observations(app,client)
    response=client.post('/api/observations/'+obs[0]['id']+'/recognize',json={})
    assert response.status_code==200
    assert response.json['identity_proposal']['status']=='unresolved'
    proposal = response.json['identity_proposal']
    if shutil.which('tesseract'):
        assert 'TEST' in proposal['evidence_text'].upper()
    else:
        assert proposal['evidence_text'] == ''
        assert 'Local text extraction is unavailable.' in proposal['uncertainty']
    corrected=client.patch('/api/observations/'+obs[0]['id'],json={'bbox':[0,0,.5,.5]})
    assert corrected.json['identity_proposal']['evidence_text']==''
    assert corrected.json['crop_revision']==1


def test_observation_limit(app,client,monkeypatch):
    import server.app as module
    monkeypatch.setattr(module, 'MAX_OBSERVATIONS', 25)
    obs=observations(app,client)
    for _ in range(23):
        assert client.post('/api/observations',json={'photo_id':obs[0]['photo_id'],'bbox':[0,0,.1,.1]}).status_code==201
    assert client.post('/api/observations',json={'photo_id':obs[0]['photo_id'],'bbox':[0,0,.1,.1]}).status_code==409


def test_photo_review_provenance_and_export(app, client):
    c = card(client, observations(app, client)[0], evidence_state='photo_reviewed',
             visual_description='Blue border and white fabric window', serial_number='03/25', year='', number='', variant='', grade='', condition='')
    assert c['evidence_state'] == 'photo_reviewed'
    assert c['serial_number'] == '03/25'
    assert client.get('/api/cards/'+c['id']+'/analysis').json['valuation']['market_value_cents'] is None
    assert 'Blue border and white fabric window' in client.get('/api/export/csv').text
    c = client.patch('/api/cards/'+c['id'], json={'revision':1, 'notes':'Checked visible name'}).json
    assert c['evidence_state'] == 'photo_reviewed'
    assert client.patch('/api/cards/'+c['id'], json={'revision':2, 'evidence_state':'automatic_certification'}).status_code == 400


def test_rotated_crop_preserves_original_and_invalidates_text(app, client):
    obs = observations(app, client)
    before = client.get('/media/original/'+obs[0]['photo_id']).data
    unrotated = Image.open(io.BytesIO(client.get('/media/crop/'+obs[0]['id']).data))
    changed = client.patch('/api/observations/'+obs[0]['id'], json={'rotation':90}).json
    rotated = Image.open(io.BytesIO(client.get('/media/crop/'+obs[0]['id']).data))
    assert rotated.size == unrotated.size[::-1]
    assert changed['identity_proposal']['evidence_text'] == ''
    assert changed['crop_revision'] == 1
    assert client.get('/media/original/'+obs[0]['photo_id']).data == before
    assert client.patch('/api/observations/'+obs[0]['id'], json={'rotation':45}).status_code == 400


def test_cover_must_belong_to_same_physical_card(app, client):
    obs = observations(app, client)
    a = card(client, obs[0])
    b = card(client, obs[1])
    assert a['primary_observation_id'] == obs[0]['id']
    assert client.patch('/api/cards/'+a['id'], json={'revision':1, 'primary_observation_id':obs[1]['id']}).status_code == 409
    extra = client.post('/api/observations', json={'photo_id':obs[0]['photo_id'], 'bbox':[0,0,.1,.2], 'rotation':90}).json
    client.post('/api/cards/'+a['id']+'/link', json={'observation_id':extra['id'], 'side':'front'})
    changed = client.patch('/api/cards/'+a['id'], json={'revision':1, 'primary_observation_id':extra['id']}).json
    assert changed['primary_observation_id'] == extra['id']
    assert len(app.store.all('card')) == 2


def test_dense_photo_can_propose_more_than_25_cards(tmp_path):
    from server.recognition import detect
    image = Image.new('RGB', (1600, 1300), '#eeeedd')
    draw = ImageDraw.Draw(image)
    for row in range(5):
        for col in range(6):
            x, y = 35+col*260, 25+row*255
            draw.rectangle((x,y,x+165,y+215), fill='#485977')
            draw.rectangle((x+25,y+35,x+65,y+70), fill='white')
    path = tmp_path/'dense-synthetic.jpg'
    image.save(path)
    result = detect(path)
    assert len(result['cards']) == 30
    assert not result['truncated']
    assert all(box[2]*box[3] < .05 for box in result['cards'])


def test_interrupted_request_retains_no_originals(app,client):
    from werkzeug.test import EnvironBuilder, run_wsgi_app
    environment=EnvironBuilder(path='/api/photos',method='POST',data=b'partial',headers={'X-SportsCards-Token':client.get('/api/state').json['token']}).get_environ()
    environment['CONTENT_LENGTH']='100'
    _, status, _ = run_wsgi_app(app,environment,buffered=True)
    assert status.startswith('400')
    assert not app.store.all('photo')
    assert not list((app.store.root/'staging').iterdir())


def test_tracking_urls_do_not_create_independent_sales():
    template=dict(id='one',**IDENTITY,status='sold',currency='USD',sold_date=dt.date.today().isoformat(),price_cents=1000,shipping_cents=0)
    sources=['https://www.ebay.com/itm/123456789012','https://www.ebay.com/itm/test-card/123456789012?utm_source=test','https://ebay.com/itm/123456789012#details']
    value=value_card(IDENTITY,[dict(template,id=str(i),source_url=url) for i,url in enumerate(sources)])
    assert len(value['included'])==1
    assert value['market_value_cents'] is None


def test_reviewed_analysis_end_to_end(app, client):
    item = card(client, observations(app, client)[0])
    route = '/api/cards/'+item['id']
    review = dict(revision=1, query='Synthetic exact variant', sources=[{'url':'https://example.com/sold','label':'Synthetic source'}])
    assert client.put(route+'/research', json=dict(review,revision=0)).status_code == 409
    assert client.put(route+'/research', json=review).status_code == 200
    assert client.patch('/api/analysis-settings', json={'percent':51}).status_code == 400
    assert client.patch('/api/analysis-settings', json={'shipping_cents':-1}).status_code == 400
    assert client.patch('/api/analysis-settings', json={'shipping_cents':550}).status_code == 200
    result = client.post(route+'/comparables', json=dict(IDENTITY, status='sold', source_url='https://example.com/sold',
        sold_date=dt.date.today().isoformat(), price_cents=2000, shipping_cents=100,
        match_reviewed=True, shipping_known=True, price_status='known'))
    assert result.status_code == 201
    value = client.get(route+'/analysis').json['valuation']
    assert value['sample_count'] == 1 and value['market_value_cents'] == 2100
    assert client.get('/api/portfolio').json['summary']['valued'] == 1
    export = client.get('/api/export/analysis-csv')
    assert 'sportscards-analysis.csv' in export.headers['Content-Disposition']
    assert '2100' in export.text and 'Synthetic' not in export.text
    client.patch(route, json={'revision':1, 'variant':'Changed'})
    assert client.get('/api/portfolio').json['summary']['valued'] == 0
