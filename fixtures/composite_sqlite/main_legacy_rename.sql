PRAGMA foreign_keys=OFF;
PRAGMA legacy_alter_table=ON;
ALTER TABLE legacy_parent RENAME TO legacy_parent_v2;
PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=ON;
