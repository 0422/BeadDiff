# 2026-10-14：本次修改原因：离线验证白底图建档预设可保存、可回传且不混用售价与成本；配置损坏不得静默覆盖。
from dataclasses import replace
from io import BytesIO
import pytest
from PIL import Image
from beaddiff.assets import AssetStore
from beaddiff.listing import ListingDefaults, ListingDefaultsStore, uploaded_product
from beaddiff.miaoshou_config import MiaoshouConfig
from beaddiff.miaoshou_mapping import create_payload
from beaddiff.validation_guidance import explain_issue


def asset(tmp_path):
    raw = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(raw, format='PNG')
    return AssetStore(tmp_path).save(raw.getvalue())


def test_defaults_roundtrip_and_reject_invalid_without_overwrite(tmp_path):
    store = ListingDefaultsStore(tmp_path)
    assert not store.path.exists() and store.get().stock == '0'
    defaults = ListingDefaults(category='手工串珠', price='5.00', supply_price='2.00')
    store.save(defaults)
    before = store.path.read_bytes()
    assert ListingDefaultsStore(tmp_path).get() == defaults
    with pytest.raises(ValueError):
        store.save(replace(defaults, weight='NaN'))
    assert store.path.read_bytes() == before
    store.path.write_text('broken JSON', encoding='utf-8')
    with pytest.raises(ValueError, match='设置 → 白底图 Listing'):
        store.get()
    assert store.path.read_text(encoding='utf-8') == 'broken JSON'


@pytest.mark.parametrize('patch', [
    {'stock': '-1'}, {'stock': '1.5'}, {'stock': '100000'}, {'price': '0'}, {'supply_price': 'Infinity'},
    {'dimensions': '10*0*2'}, {'main_count': True}, {'detail_count': 0}, {'spec1': 'a;b'}, {'code_prefix': '../a'},
])
def test_unsafe_defaults_fail_before_product_creation(patch):
    assert replace(ListingDefaults(category='beads'), **patch).problems(require_category=True)


def test_uploaded_defaults_pass_local_save_and_erp_preflight(tmp_path):
    picture = asset(tmp_path)
    defaults = ListingDefaults(category='beads', price='9.00', supply_price='3.00')
    first = uploaded_product([picture], {'color': 'white'}, defaults)
    second = uploaded_product([picture], {}, defaults)
    assert first.issues() == []
    assert first.main_code != second.main_code
    assert first.skus[0].platform_sku != second.skus[0].platform_sku
    assert first.attributes == {'颜色': 'white'}
    assert first.package_dimensions == first.skus[0].dimensions == '10*10*2'
    assert first.skus[0].stock == '0' and not first.certificate
    payload = create_payload(first, MiaoshouConfig(), allow_local_images=True)
    assert payload['itemNum'] == first.main_code
    assert payload['price'] == 3
    sku = next(iter(payload['skuMap'].values()))
    assert sku['price'] == 9 and sku['stock'] == 0
    assert payload['imgUrls'] == [picture.uri]


@pytest.mark.parametrize('error,location', [
    ('图床缓存读取失败', '设置 → 系统 → 数据目录'),
    ('SKU 重量 KG 无效', '物流信息'),
    ('SKU 图片无效', '图片 → SKU 图片'),
    ('sizeChart 超过上限', '图片 → 产品尺码表'),
    ('请核对币种', '销售属性'),
    ('结果未知，请先核对', '回传日志'),
    ('AppKey 未设置', '妙手开放平台 · 公共采集箱'),
    ('USD 汇率未填写', '人工确认的人民币汇率'),
    ('主编号不能为空', '基本信息 → 产品主编号'),
    ('图片模型未配置', '设置 → AI 模型'),
    ('说明书链接无效', '认证附件'),
])
def test_error_guidance_points_to_actual_page_and_field(error, location):
    message = explain_issue(error)
    assert error in message and location in message
    assert explain_issue(message) == message
