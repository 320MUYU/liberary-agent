import assert from 'node:assert/strict'
import test from 'node:test'
import {
  reservationError,
  spaceAvailability,
  reservationHeading
} from '../src/utils/spaceReservation.js'

const valid = { date: '2030-10-20', start: '14:00', end: '16:00', people: 3, purpose: '课程讨论' }
test('reservation form requires explicit date, interval, capacity and purpose', () => {
  const now = new Date('2030-10-20T12:00:00')
  assert.equal(reservationError(valid, now), '')
  assert.match(reservationError(valid, new Date('2030-10-20T12:00:01')), /两小时/)
  for (const invalid of [
    { date: '' },
    { start: '' },
    { end: '13:00' },
    { people: 0 },
    { people: true },
    { purpose: ' ' },
    { date: '2030-02-30' }
  ]) {
    assert.ok(reservationError({ ...valid, ...invalid }, now))
  }
})
test('availability reports every server reason and does not promise approval', () => {
  assert.match(spaceAvailability({ can_reserve: true }), /可申请/)
  assert.match(
    spaceAvailability({
      can_reserve: false,
      unavailable_reasons: ['maintenance', 'capacity', 'approved_conflict', 'too_late']
    }),
    /维护.*人数.*通过.*两小时/
  )
  assert.match(reservationHeading('reservation_pending'), /待管理员审核/)
  assert.match(reservationHeading('reservation_approved'), /通过/)
})
