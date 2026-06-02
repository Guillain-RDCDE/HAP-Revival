-- hdd_browse.db
-- =============================================
CREATE TABLE FT0002 (
    PROP3601        INTEGER NOT NULL, /* 01.object id        */ 
    PROP304B        INTEGER NOT NULL, /* 02.codec            */ 
    PROP3046        INTEGER NOT NULL, /* 03.playing count    */ 
    PROP3047        INTEGER NOT NULL, /* 04.duration         */ 
    PROP3048        INTEGER NOT NULL, /* 05.sample rate      */ 
    PROP304C        INTEGER NOT NULL, /* 06.audio bitrate    */ 
    PROP1086        INTEGER NOT NULL, /* 07.import type      */ 
    PROP7045        INTEGER NOT NULL, /* 08.genre(id)        */ 
    PROP7052        INTEGER NOT NULL, /* 09.artist(id)       */ 
    PROP706F        INTEGER NOT NULL, /* 10.composer(id)     */ 
    PROP7070        INTEGER NOT NULL, /* 11.lyricist(id)     */ 
    PROP10E7        INTEGER NOT NULL, /* 12.sm channel num   */ 
    PROP08E8        INTEGER NOT NULL, /* 13.sm channel 1     */ 
    PROP08E9        INTEGER NOT NULL, /* 14.sm channel 2     */ 
    PROP08EA        INTEGER NOT NULL, /* 15.sm channel 3     */ 
    PROP58DF        INTEGER NOT NULL, /* 16.possible play    */ 
    PROP7020        TEXT NOT NULL,    /* 17.track name       */ 
    PROP2053        INTEGER NOT NULL, /* 18.track no         */ 
    PROP6844        INTEGER NOT NULL, /* 19.release date     */ 
    PROP087E        INTEGER NOT NULL, /* 20.rating type      */ 
    PROPAA00        TEXT,             /* 21.track name(yomi) */ 
    PROP10DE        INTEGER NOT NULL, /* 22.audio bit width  */ 
    PROPB2BB        INTEGER NOT NULL, /* 23.album id (ref)   */ 
    PROP207B        INTEGER NOT NULL, /* 24.update flag      */ 
    PROP7065        TEXT NOT NULL,    /* 25.track name(sort) */ 
    PROP7221        TEXT NOT NULL, PROPAA01        INTEGER NOT NULL DEFAULT 0/* genre edit flag*/, PROPAA02        INTEGER NOT NULL DEFAULT 0/* artist edit flag*/, PROPAA03        INTEGER NOT NULL DEFAULT 0/* track name edit flag*/, PROPAA04        INTEGER NOT NULL DEFAULT 0/* release edit flag*/, PROPAA05        INTEGER NOT NULL DEFAULT 0/* track no edit flag*/, PROPAA06        INTEGER NOT NULL DEFAULT 0/* album edit flag*/, PROP10DD        INTEGER NOT NULL DEFAULT 0/* multi channel*/, PROP58D3        INTEGER NOT NULL DEFAULT 0/* drm exist flag*/, PROP7007        TEXT/* file name          */, PROPAA07        TEXT/* file name(sort)    */, PROPAA08        TEXT/* file name(initial) */, PROP3006        INTEGER NOT NULL DEFAULT 0/* parent id */, PROP10A3        INTEGER NOT NULL DEFAULT 1 /* DiscNumber */, PROPAA09        INTEGER NOT NULL DEFAULT 0 /* disc number edit flag*/, PROPAA0A        INTEGER NOT NULL DEFAULT -1 /* sm channel 1 backup */, PROPAA0B        INTEGER NOT NULL DEFAULT -1 /* sm channel 2 backup */, PROPAA0C        INTEGER NOT NULL DEFAULT -1 /* sm channel 3 backup */, PROPAA0D        INTEGER NOT NULL DEFAULT 0 /* sm edit flag */, PROPAA0E        INTEGER NOT NULL DEFAULT 0  /* play order */,    /* 26.track name(initial)*/ 
    PRIMARY KEY(PROP3601)                                    
                                                             
);
CREATE INDEX idx_FT0002_PROP3046 ON FT0002(PROP3046);
CREATE INDEX idx_FT0002_PROP1086 ON FT0002(PROP1086);
CREATE INDEX idx_FT0002_PROP7045 ON FT0002(PROP7045);
CREATE INDEX idx_FT0002_PROP7052 ON FT0002(PROP7052);
CREATE INDEX idx_FT0002_PROP706F ON FT0002(PROP706F);
CREATE INDEX idx_FT0002_PROP7070 ON FT0002(PROP7070);
CREATE INDEX idx_FT0002_PROP58DF ON FT0002(PROP58DF);
CREATE INDEX idx_FT0002_PROP6844 ON FT0002(PROP6844);
CREATE INDEX idx_FT0002_PROP087E ON FT0002(PROP087E);
CREATE INDEX idx_FT0002_PROP7065 ON FT0002(PROP7065);
CREATE INDEX idx_FT0002_PROP7221 ON FT0002(PROP7221);
CREATE TABLE FT000A (
    PROP3601        INTEGER NOT NULL, /* object id        */ 
    PROP6844        INTEGER NOT NULL, /* release date     */ 
    PROP78D9        BLOB,             /* thumbnail        */ 
    PROPAA10        INTEGER NOT NULL, /* exist thumb flag */ 
    PROP7020        TEXT,             /* album name       */ 
    PROPAA11        TEXT,             /* album name(yomi) */ 
    PROP7055        TEXT,             /* album artist name*/ 
    PROP7065        TEXT,             /* album name(sort) */ 
    PROP7221        TEXT, PROPAA12        INTEGER NOT NULL DEFAULT 0/* album image edit flag*/, PROP30C5        INTEGER NOT NULL DEFAULT 0 /* parent id for folder */,             /* album name(initial) */ 
    PRIMARY KEY(PROP3601)                                    
                                                             
);
CREATE INDEX idx_FT000A_PROP6844 ON FT000A(PROP6844);
CREATE INDEX idx_FT000A_PROP7065 ON FT000A(PROP7065);
CREATE INDEX idx_FT000A_PROP7221 ON FT000A(PROP7221);
CREATE TABLE FT4502 (
    PROP3601        INTEGER NOT NULL, /* id                 */ 
    PROP7020        TEXT,             /* genre name         */ 
    PROP1086        INTEGER NOT NULL, /* add type           */ 
    PROPAA20        TEXT,             /* genre name(yomi)   */ 
    PROP7065        TEXT,             /* genre name(sort)   */ 
    PROP7221        TEXT,             /* genre name(initial)*/ 
    PRIMARY KEY(PROP3601)                                      
);
CREATE INDEX idx_FT4502_PROP7065 ON FT4502(PROP7065);
CREATE INDEX idx_FT4502_PROP7221 ON FT4502(PROP7221);
CREATE TABLE FT5202 (
    PROP3601        INTEGER NOT NULL, /* id                 */ 
    PROP7020        TEXT,             /* artist             */ 
    PROP1086        INTEGER NOT NULL, /* add type           */ 
    PROPAA30        TEXT,             /* artist name(yomi)  */ 
    PROP7065        TEXT,             /* artist name(sort)  */ 
    PROP7221        TEXT,             /* artist name(initial)*/ 
    PRIMARY KEY(PROP3601)                                      
);
CREATE INDEX idx_FT5202_PROP7065 ON FT5202(PROP7065);
CREATE INDEX idx_FT5202_PROP7 ON FT5202(PROP7221);
CREATE TABLE FT6F02 (
    PROP3601        INTEGER NOT NULL, /* id                   */ 
    PROP7020        TEXT,             /* composer             */ 
    PROP1086        INTEGER NOT NULL, /* add type             */ 
    PROPAA40        TEXT,             /* composer name(yomi)  */ 
    PROP7065        TEXT,             /* composer name(sort)  */ 
    PROP7221        TEXT,             /* composer name(initial)*/ 
    PRIMARY KEY(PROP3601)                                        
);
CREATE INDEX idx_FT6F02_PROP7065 ON FT6F02(PROP7065);
CREATE INDEX idx_FT6F02_PROP7221 ON FT6F02(PROP7221);
CREATE TABLE FT7002 (
    PROP3601        INTEGER NOT NULL, /* id                   */ 
    PROP7020        TEXT,             /* lyricist             */ 
    PROP1086        INTEGER NOT NULL, /* add type             */ 
    PROPAA50        TEXT,             /* lyricist name(yomi)  */ 
    PROP7065        TEXT,             /* lyricist name(sort)  */ 
    PROP7221        TEXT,             /* lyricist name(initial)*/ 
    PRIMARY KEY(PROP3601)                                        
);
CREATE INDEX idx_FT7002_PROP7065 ON FT7002(PROP7065);
CREATE INDEX idx_FT7002_PROP7221 ON FT7002(PROP7221);
CREATE TABLE FTF002 (
    PROP3601        INTEGER NOT NULL, /* genre/artist id  */ 
    PROP3006        INTEGER NOT NULL, /* group id         */ 
    PROP705E        INTEGER NOT NULL, /* group type       */ 
    PRIMARY KEY(PROP3601,PROP3006,PROP705E)              
);
CREATE TABLE FTF003 (
    PROP3601        INTEGER NOT NULL, /* list id              */ 
    PROP7020        TEXT,             /* playlist name        */ 
    PROP106E        INTEGER NOT NULL, /* track num            */ 
    PROPAA70        INTEGER NOT NULL, /* modify no            */ 
    PROPAA71        TEXT,             /* playlist name (yomi) */ 
    PROP7065        TEXT,             /* playlist name (sort) */ 
    PROP7221        TEXT,             /* playlist name (initial) */ 
    PRIMARY KEY(PROP3601)                                        
);
CREATE INDEX idx_FTF003_PROP7065 ON FTF003(PROP7065);
CREATE INDEX idx_FTF003_PROP7221 ON FTF003(PROP7221);
CREATE TABLE FTF004 (
    PROP3601        INTEGER NOT NULL, /* track id     */ 
    PROP3006        INTEGER NOT NULL, /* list id      */ 
    PROP2053        INTEGER NOT NULL, /* position     */ 
    PRIMARY KEY(PROP3601,PROP3006,PROP2053)              
);
CREATE INDEX idx_FTF004_PROP2053 ON FTF004(PROP2053);
CREATE TABLE FTF0FF (
    PROP3601        INTEGER NOT NULL, /* id           */ 
    PROPFFF0        INTEGER,          /* value(int)   */ 
    PROPFFF1        TEXT,             /* value(text)  */ 
    PRIMARY KEY(PROP3601)                                
);
CREATE INDEX idx_FT0002_PROPB2BB ON FT0002(PROPB2BB);
CREATE TABLE FT0000 (
    PROP3601        INTEGER NOT NULL, /* 01.folder id         */ 
    PROP3006        INTEGER NOT NULL, /* 02.parent id         */ 
    PROP1086        INTEGER NOT NULL, /* 03.import type       */ 
    PROP7020        TEXT    NOT NULL, /* 04.folder name       */ 
    PROP7221        TEXT    NOT NULL, /* 06.folder name(initial) */ 
    PROP7023        TEXT    NOT NULL, /* 07.folder path(IDs)     */ 
    PROPAA90        TEXT    NOT NULL, /* 08.folder path(sort)    */ 
    PRIMARY KEY(PROP3601)                                    
);
CREATE INDEX idx_FT0000_P1086P7023 ON FT0000(PROP1086,PROP7023);
CREATE INDEX idx_FT0000_P7221 ON FT0000(PROP7221);
CREATE INDEX idx_FT0000_PAA90 ON FT0000(PROPAA90);
CREATE INDEX idx_FT0002_P3006 ON FT0002(PROP3006);
CREATE INDEX idx_FT0002_PAA07 ON FT0002(PROPAA07);
CREATE INDEX idx_FT0002_PAA08 ON FT0002(PROPAA08);

-- ROW COUNTS --
-- FT0000                                   7409 rows
-- FT000A                                   5677 rows
-- FT5202                                   21849 rows
-- FT7002                                   1 rows
-- FTF003                                   0 rows
-- FTF0FF                                   5 rows
-- FT0002                                   77668 rows
-- FT4502                                   622 rows
-- FT6F02                                   7167 rows
-- FTF002                                   0 rows
-- FTF004                                   0 rows
