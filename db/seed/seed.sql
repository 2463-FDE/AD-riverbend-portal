-- Riverbend demo seed data.
-- NOTE: Maria Gonzalez appears as THREE patient rows (1042, 1330, 1588) created
-- through self-service intake with no match key. Her penicillin allergy is only
-- recorded under 1330.

INSERT INTO patients (id, name, dob, ssn, address, notes, created_at) VALUES
 (1042, 'Maria Gonzalez', '1971-03-02', '412-55-9981', '118 Maple Ave, Beverly Hills, CA 90210', 'Prefers morning appts.', '2026-06-22 09:14:06'),
 (1043, 'James O''Brien',  '1958-11-19', '501-22-7734', '42 Birch St, Riverbend, CA 90211', 'Hard of hearing.', '2026-06-22 09:17:27'),
 (1330, 'Maria Gonzales',  '1971-03-02', '412-55-9981', '118 Maple Ave, Beverly Hills, CA 90210', 'PCN allergy noted at front desk.', '2026-06-22 09:21:45'),
 (1588, 'M. Gonzalez',     '1971-02-03', '412-55-9981', '118 Maple Ave, Beverly Hills, CA 90210', '', '2026-06-22 09:55:06'),
 (1601, 'Aisha Khan',      '1989-07-14', '623-41-2210', '900 Cedar Rd, Riverbend, CA 90211', '', '2026-06-23 10:02:00');
SELECT setval('patients_id_seq', 1601, true);

INSERT INTO encounters (patient_id, encounter_type, provider, summary, allergies, medications, occurred_at) VALUES
 (1042, 'office_visit', 'Dr. Patel',  'Annual physical. Unremarkable.', '', 'lisinopril', '2026-01-12 09:00:00'),
 (1330, 'office_visit', 'Dr. Nguyen', 'Sinus infection. Prescribed antibiotic.', 'penicillin', 'amoxicillin', '2026-03-04 11:30:00'),
 (1588, 'lab',          'Lab',        'CBC panel within normal limits.', '', '', '2026-05-19 08:15:00'),
 (1043, 'office_visit', 'Dr. Patel',  'Hearing aid follow-up.', '', '', '2026-02-20 14:00:00'),
 (1601, 'office_visit', 'Dr. Nguyen', 'New patient intake.', 'none known', '', '2026-06-23 10:30:00');

INSERT INTO records (encounter_id, patient_id, kind, body, created_at) VALUES
 (1, 1042, 'note', 'Patient in good health.', '2026-01-12 09:20:00'),
 (2, 1330, 'note', 'Penicillin allergy confirmed. Switched to non-PCN class.', '2026-03-04 11:45:00'),
 (3, 1588, 'lab_result', 'WBC 6.1, RBC 4.7, Hgb 14.2.', '2026-05-19 09:00:00'),
 (4, 1043, 'note', 'Hearing stable.', '2026-02-20 14:20:00'),
 (5, 1601, 'note', 'Established care.', '2026-06-23 10:50:00');

-- Two confirmed appointments for the SAME slot, ~400ms apart (retry race).
INSERT INTO appointments (patient_id, slot_id, status, created_at) VALUES
 (1042, 88231, 'confirmed', '2026-06-22 09:31:04.120'),
 (1588, 88231, 'confirmed', '2026-06-22 09:31:04.519'),
 (1043, 88240, 'confirmed', '2026-06-22 10:05:00.000');

INSERT INTO consents (patient_id, kind) VALUES
 (1042, 'npp_ack'), (1042, 'treatment_consent'),
 (1043, 'npp_ack'), (1601, 'npp_ack');

-- "audit" rows are really app INFO logs with PHI in them.
INSERT INTO audit_logs (actor, message) VALUES
 ('intake-service', 'POST /intake body={"name":"Maria Gonzalez","dob":"1971-03-02","ssn":"412-55-9981"}'),
 ('records-service', 'GET /patients/1042/records 200');
