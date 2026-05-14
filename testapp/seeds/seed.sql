-- Reference seed data — 3 categories, 5 products, 3 reviews.
-- Applied by migration 002_seed_data.py; this file is kept for documentation
-- and for ad-hoc manual seeding (psql -f seeds/seed.sql).
-- SEED_PRODUCT_COUNT = 5: kept in sync with tests/e2e.py.

INSERT INTO categories (name, slug) VALUES
  ('Electronics', 'electronics'),
  ('Books',       'books'),
  ('Clothing',    'clothing')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO products (name, description, category_id, price, stock, discount_pct)
SELECT p.name, p.description, c.id, p.price, p.stock, p.discount_pct
FROM (VALUES
  ('Wireless Headphones',      'Noise-cancelling, 30 h battery',         'electronics', 79.99,  20, 15.00),
  ('Mechanical Keyboard',      'Compact 75 % layout, tactile switches',   'electronics', 129.99, 15,  0.00),
  ('Clean Code',               'Handbook of Agile Software Craftsmanship', 'books',       34.99,  50, 20.00),
  ('The Pragmatic Programmer', 'Your Journey to Mastery',                  'books',       39.99,  45, 10.00),
  ('Tech Hoodie',              'Soft-shell, sizes XS–3XL',                 'clothing',    49.99,  30,  0.00)
) AS p(name, description, category_slug, price, stock, discount_pct)
JOIN categories c ON c.slug = p.category_slug;

INSERT INTO reviews (product_id, author, rating, body)
SELECT p.id, r.author, r.rating, r.body
FROM products p
JOIN (VALUES
  ('Wireless Headphones',      'alice',   5, 'Outstanding sound quality.'),
  ('Wireless Headphones',      'bob',     4, 'Great but a bit expensive.'),
  ('Clean Code',               'charlie', 5, 'Every developer should read this.')
) AS r(product_name, author, rating, body) ON r.product_name = p.name;
