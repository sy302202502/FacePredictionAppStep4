package com.faceprediction.service;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.LocalTime;

import org.junit.jupiter.api.Test;

class SnapshotServiceTest {

    @Test
    void 発走が近づいたレースは上書きしない() {
        // 11R は 15:10 から上書きしない（実際の発走は 15:25〜15:45 ごろ）
        assertFalse(SnapshotService.isFrozen("202605050311", LocalTime.of(15, 9)));
        assertTrue(SnapshotService.isFrozen("202605050311", LocalTime.of(15, 10)));
        assertTrue(SnapshotService.isFrozen("202605050311", LocalTime.of(18, 0)));
        // 9R は 13:50 から
        assertFalse(SnapshotService.isFrozen("202603030309", LocalTime.of(13, 30)));
        assertTrue(SnapshotService.isFrozen("202603030309", LocalTime.of(13, 50)));
    }

    @Test
    void 海外レースや形の違う番号は対象外() {
        assertFalse(SnapshotService.isFrozen("2026C8010105", LocalTime.of(23, 0)));
        assertFalse(SnapshotService.isFrozen(null, LocalTime.of(23, 0)));
        assertFalse(SnapshotService.isFrozen("202605050399", LocalTime.of(23, 0)));
    }
}
