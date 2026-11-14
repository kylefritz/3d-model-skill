-- Notes sent from the viewer's Comment button. Read and answered with tools/comments.py.
CREATE TABLE comments (
  id TEXT PRIMARY KEY,                 -- c_<time36><rand>
  created TEXT NOT NULL,               -- ISO 8601 UTC
  model TEXT NOT NULL,                 -- the contract's name (model/options.yaml `name:`)
  author TEXT,                         -- whatever name the sender typed (optional)
  body TEXT NOT NULL DEFAULT '',
  link TEXT NOT NULL,                  -- deep link: the design, light, state and camera it was written from
  show TEXT NOT NULL,                  -- proposed | existing
  cam TEXT NOT NULL,                   -- px,py,pz,tx,ty,tz (viewer metres, glTF Y-up)
  pins TEXT NOT NULL DEFAULT '[]',     -- [{n, x, y, z, id, label}]; id/label from the tapped piece
  strokes INTEGER NOT NULL DEFAULT 0,  -- pen strokes drawn (they exist only in the image)
  image TEXT,                          -- data:image/jpeg;base64 snapshot: view + pen + pins
  status TEXT NOT NULL DEFAULT 'open', -- open | done | wontfix
  reply TEXT,                          -- the answer, shown in the viewer (public)
  replied TEXT
);
CREATE INDEX comments_model ON comments (model, created);
