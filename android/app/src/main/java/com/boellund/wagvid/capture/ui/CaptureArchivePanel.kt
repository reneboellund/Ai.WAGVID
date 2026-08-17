package com.boellund.wagvid.capture.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.boellund.wagvid.capture.data.CaptureDao

@Composable
fun CaptureArchivePanel(
    dao: CaptureDao,
    expanded: Boolean,
    onToggle: () -> Unit,
) {
    val rows by dao.archiveRows().collectAsState(initial = emptyList())
    Surface(color = Color(0xDD07101E)) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Lokalt arkiv · ${rows.size}", color = Color.White)
                Button(onClick = onToggle) { Text(if (expanded) "Skjul" else "Vis") }
            }
            if (expanded) {
                rows.take(8).forEach { row ->
                    val upload = row.uploadState ?: "lokal"
                    val error = row.lastError?.takeIf { it.isNotBlank() }?.let { " · fejl: $it" } ?: ""
                    Text(
                        "${row.gymnastName} · ${row.kind} · $upload$error",
                        color = Color.White,
                    )
                }
                if (rows.isEmpty()) Text("Ingen lokale optagelser endnu", color = Color.White)
            }
        }
    }
}
