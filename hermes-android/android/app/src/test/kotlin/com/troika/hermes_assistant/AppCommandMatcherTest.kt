package com.troika.hermes_assistant

import org.junit.Assert.*
import org.junit.Test

class AppCommandMatcherTest {
    @Test fun projectInstructionsAreNotAppLaunches() {
        val prompt = "Разработай проект: калькулятор. Используй troika_create_project. " +
            "Включи исходники, README и тесты. Для JavaScript основной файл index.js."
        assertNull(AppCommandMatcher.target(prompt))
        assertNull(AppCommandMatcher.target("Объясни, как открыть Twitter"))
        assertNull(AppCommandMatcher.target("Создай код и включи фонарик в примере"))
    }

    @Test fun explicitLaunchesRemainAvailable() {
        assertEquals("x", AppCommandMatcher.target("Открой X"))
        assertEquals("твиттер", AppCommandMatcher.target("Тройка, открой приложение Твиттер, пожалуйста."))
        assertEquals("телеграм", AppCommandMatcher.target("Запусти Телеграм"))
    }

    @Test fun singleLetterAliasNeverMatchesInsideAFilename() {
        assertFalse(AppCommandMatcher.matchesAlias("index.js", "x"))
        assertFalse(AppCommandMatcher.matchesAlias("excel", "x"))
        assertFalse(AppCommandMatcher.matchesAlias("twitter tutorial", "twitter"))
        assertTrue(AppCommandMatcher.matchesAlias("X", "x"))
    }
}
