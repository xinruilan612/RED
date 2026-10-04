'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const profile = require('../frontend/account_profile.js');

test('profile choices vary by positioning and platform', () => {
  const photo = profile.options('摄影 / 摄影服务', 'xiaohongshu');
  const clothing = profile.options('服饰 / 穿搭', 'xiaohongshu');
  const shortVideo = profile.options('摄影 / 摄影服务', 'douyin');
  assert.ok(photo.pillars.includes('修图前后对比'));
  assert.ok(!clothing.pillars.includes('修图前后对比'));
  assert.ok(clothing.pillars.includes('穿搭展示'));
  assert.ok(shortVideo.pillars.includes('拍摄过程短视频'));
  assert.notDeepEqual(photo.goals, clothing.goals);
  assert.notDeepEqual(photo.resources.equipment, clothing.resources.equipment);
  assert.ok(profile.options('美妆 / 护肤', 'xiaohongshu').banned.includes('保证祛痘'));
});

test('switching direction removes stale suggested values but preserves custom values', () => {
  const result = profile.valuesFor('pillars', '修图前后对比、我自己的栏目', '摄影 / 摄影服务', 'xiaohongshu', '服饰 / 穿搭', 'xiaohongshu');
  assert.deepEqual(result, ['我自己的栏目']);
});

test('category switching accepts checkbox arrays as well as persisted strings', () => {
  assert.deepEqual(profile.splitList([' 穿搭展示 ', '']), ['穿搭展示']);
  assert.deepEqual(profile.valuesFor('pillars', ['修图前后对比', '我自己的栏目'], '摄影 / 摄影服务', 'xiaohongshu', '服饰 / 穿搭', 'xiaohongshu'), ['我自己的栏目']);
});

test('positioning round-trips a selected category and custom detail', () => {
  const value = profile.positionValue('摄影 / 摄影服务', '人像约拍');
  assert.deepEqual(profile.positioningParts(value), { category: '摄影 / 摄影服务', detail: '人像约拍' });
});

test('platform-specific account selection preserves old account identity', () => {
  const current = { id: 'xhs-1', platform: 'xiaohongshu' };
  const accounts = [current, { id: 'dy-1', platform: 'douyin', name: 'Rul', aliases: ['Rul'] }];
  assert.equal(profile.saveTarget(current, accounts, 'Rul', 'xiaohongshu'), 'xhs-1');
  assert.equal(profile.saveTarget(current, accounts, 'Rul', 'douyin'), 'dy-1');
  assert.equal(profile.saveTarget(current, [current], 'Rul', 'douyin'), '');
  assert.equal(current.platform, 'xiaohongshu');
});
