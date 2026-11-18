"""Run the shared Kotlin app resolver with installed-app inventories."""

import os
from tests.troika_product.test_android_command_privacy import (
    SOURCE, _jdk, _kotlin_compiler, _compile_kotlin, _run,
)


def test_installed_aliases_and_ambiguous_labels(tmp_path):
    java, _ = _jdk()
    compiler = _kotlin_compiler()
    harness = tmp_path / "AppNameHarness.kt"
    harness.write_text('''
package com.troika.hermes_assistant
fun main() {
    val apps = listOf(
        "org.telegram.messenger" to "Telegram",
        "com.android.chrome" to "Chrome",
        "com.android.settings" to "Settings",
        "notes.one" to "Work Notes",
        "notes.two" to "Personal Notes",
    )
    val installed = apps.map { it.first }.toSet()
    fun resolve(q: String) = AppNameResolver.resolve(q, apps) { it in installed }
    check(resolve("ТЕЛЕГРАМ") == "org.telegram.messenger")
    check(resolve(" тг ") == "org.telegram.messenger")
    check(resolve("настройки") == "com.android.settings")
    check(resolve("браузер") == "com.android.chrome")
    check(resolve("org.telegram.messenger") == "org.telegram.messenger")
    check(resolve("Work   Notes") == "notes.one")
    check(resolve("Personal") == "notes.two")
    check(resolve("Notes") == null)
    check(resolve("not installed") == null)
    check(resolve("whatsapp") == null)
    check(resolve("сделай что-нибудь в телеграме") == null)
    check(resolve("") == null)
    println("APP_NAME_RESOLVER_OK")
}
''', encoding="utf-8")
    classes = tmp_path / "classes"
    classes.mkdir()
    _compile_kotlin(java, compiler, [compiler[1], compiler[-1]],
                    [SOURCE / "AppNameResolver.kt", harness], classes, tmp_path)
    output = _run([java, "-cp", os.pathsep.join(map(str, [classes, compiler[1]])),
                   "com.troika.hermes_assistant.AppNameHarnessKt"], tmp_path)
    assert "APP_NAME_RESOLVER_OK" in output
