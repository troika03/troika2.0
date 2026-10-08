package com.troika.hermes_assistant

/** App launches require a whole, explicit command, never a verb inside a task. */
object AppCommandMatcher {
    private val command = Regex(
        "^(?:(?:тройка|troika)[, ]+)?(?:пожалуйста[, ]+)?" +
            "(?:открой|открыть|запусти|запустить|включи|включить|загрузи|покажи)\\s+" +
            "(?:приложение\\s+)?([^\\n.!?;]+?)(?:[, ]+пожалуйста)?[.!?]*$",
        RegexOption.IGNORE_CASE,
    )

    fun target(text: String): String? = command.matchEntire(text.trim())
        ?.groupValues?.get(1)?.trim()?.lowercase()?.takeIf { it.length in 1..50 }

    fun matchesAlias(target: String, alias: String): Boolean =
        target.trim().equals(alias.trim(), ignoreCase = true)
}
