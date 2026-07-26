-- Vocabulary as data: surface forms seen in marketplace text mapped to canonical
-- attribute values. The matcher loads this once per process; growing coverage is
-- a data change, not a code change.
--
-- Catalogue makes/models are NOT duplicated here (they come from the vehicle
-- table). This table holds: abbreviations, misspellings, multi-word phrases, and
-- a small reference list of common Australian-market makes/models that are NOT
-- in the catalogue. That reference list is what lets the matcher say "Ford
-- Ranger" is a real vehicle that is definitely absent (null with confidence 10)
-- rather than merely unrecognised text (null with low confidence).
--
-- strength: 'weak' signals hint an attribute but must never generate a conflict
-- on their own (e.g. a TSI engine code hints Petrol).

CREATE TABLE IF NOT EXISTS alias (
  alias_text TEXT PRIMARY KEY,
  attribute  TEXT NOT NULL CHECK (attribute IN
              ('make', 'model', 'badge', 'transmission', 'fuel', 'drive')),
  canonical  TEXT NOT NULL,
  strength   TEXT NOT NULL DEFAULT 'strong' CHECK (strength IN ('strong', 'weak'))
);

INSERT INTO alias (alias_text, attribute, canonical, strength) VALUES
  -- makes: abbreviations and misspellings of catalogue makes
  ('vw',                'make', 'Volkswagen', 'strong'),
  ('volkswagon',        'make', 'Volkswagen', 'strong'),
  -- makes: common AU-market makes not in the catalogue (absence reference list)
  ('ford',              'make', 'Ford', 'strong'),
  ('mazda',             'make', 'Mazda', 'strong'),
  ('holden',            'make', 'Holden', 'strong'),
  ('hyundai',           'make', 'Hyundai', 'strong'),
  ('kia',               'make', 'Kia', 'strong'),
  ('nissan',            'make', 'Nissan', 'strong'),
  ('mitsubishi',        'make', 'Mitsubishi', 'strong'),
  ('honda',             'make', 'Honda', 'strong'),
  ('subaru',            'make', 'Subaru', 'strong'),
  ('isuzu',             'make', 'Isuzu', 'strong'),
  ('suzuki',            'make', 'Suzuki', 'strong'),
  ('bmw',               'make', 'BMW', 'strong'),
  ('audi',              'make', 'Audi', 'strong'),
  ('mercedes',          'make', 'Mercedes-Benz', 'strong'),
  ('mercedes-benz',     'make', 'Mercedes-Benz', 'strong'),
  ('lexus',             'make', 'Lexus', 'strong'),
  ('skoda',             'make', 'Skoda', 'strong'),
  ('jeep',              'make', 'Jeep', 'strong'),
  ('tesla',             'make', 'Tesla', 'strong'),
  ('mg',                'make', 'MG', 'strong'),
  ('ldv',               'make', 'LDV', 'strong'),
  -- models: variant spellings of catalogue models
  ('rav 4',             'model', 'RAV4', 'strong'),
  ('rav-4',             'model', 'RAV4', 'strong'),
  -- models: common AU-market models not in the catalogue (absence reference list)
  ('ranger',            'model', 'Ranger', 'strong'),
  ('corolla',           'model', 'Corolla', 'strong'),
  ('hilux',             'model', 'HiLux', 'strong'),
  ('landcruiser',       'model', 'LandCruiser', 'strong'),
  ('land cruiser',      'model', 'LandCruiser', 'strong'),
  ('prado',             'model', 'Prado', 'strong'),
  ('yaris',             'model', 'Yaris', 'strong'),
  ('commodore',         'model', 'Commodore', 'strong'),
  ('navara',            'model', 'Navara', 'strong'),
  ('triton',            'model', 'Triton', 'strong'),
  ('outlander',         'model', 'Outlander', 'strong'),
  ('civic',             'model', 'Civic', 'strong'),
  ('i30',               'model', 'i30', 'strong'),
  ('cx-5',              'model', 'CX-5', 'strong'),
  ('polo',              'model', 'Polo', 'strong'),
  ('passat',            'model', 'Passat', 'strong'),
  ('touareg',           'model', 'Touareg', 'strong'),
  -- transmission
  ('auto',              'transmission', 'Automatic', 'strong'),
  ('automatic',         'transmission', 'Automatic', 'strong'),
  ('manual',            'transmission', 'Manual', 'strong'),
  ('man',               'transmission', 'Manual', 'weak'),
  -- fuel
  ('petrol',            'fuel', 'Petrol', 'strong'),
  ('gasoline',          'fuel', 'Petrol', 'strong'),
  ('unleaded',          'fuel', 'Petrol', 'strong'),
  ('diesel',            'fuel', 'Diesel', 'strong'),
  ('hybrid',            'fuel', 'Hybrid-Petrol', 'strong'),
  ('hybrid-petrol',     'fuel', 'Hybrid-Petrol', 'strong'),
  -- drive ('2wd' deliberately omitted: ambiguous between FWD and RWD)
  ('4x4',               'drive', 'Four Wheel Drive', 'strong'),
  ('4wd',               'drive', 'Four Wheel Drive', 'strong'),
  ('awd',               'drive', 'Four Wheel Drive', 'strong'),
  ('fwd',               'drive', 'Front Wheel Drive', 'strong'),
  ('rwd',               'drive', 'Rear Wheel Drive', 'strong'),
  ('four wheel drive',  'drive', 'Four Wheel Drive', 'strong'),
  ('all wheel drive',   'drive', 'Four Wheel Drive', 'strong'),
  ('front wheel drive', 'drive', 'Front Wheel Drive', 'strong'),
  ('rear wheel drive',  'drive', 'Rear Wheel Drive', 'strong'),
  -- badge tokens: divergent surface forms only (canonical badge vocabulary
  -- comes from the vehicle table itself)
  ('h/line',            'badge', 'highline', 'strong'),
  ('hline',             'badge', 'highline', 'strong'),
  ('e/d',               'badge', 'edition', 'strong'),
  ('rline',             'badge', 'r-line', 'strong'),
  ('r line',            'badge', 'r-line', 'strong'),
  ('sports',            'badge', 'sport', 'strong')
ON CONFLICT (alias_text) DO NOTHING;
