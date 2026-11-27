package com.estehangettt.motogp.ui

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.estehangettt.motogp.data.EventResponse
import com.estehangettt.motogp.data.scraper.MotoMundoScraper
import com.estehangettt.motogp.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailScreen(
    event: EventResponse, 
    onBackClick: () -> Unit, 
    onSessionClick: (String) -> Unit
) {
    val topImageUrl = event.assets?.find { it.type == "TOP" || it.type == "BACKGROUND" }?.path
    val flagUrl = event.assets?.find { it.type == "FLAG" }?.path
    
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var loadingSession by remember { mutableStateOf<String?>(null) }
    var matchStatus by remember { mutableStateOf("") }
    val scraper = remember { MotoMundoScraper() }

    Box(modifier = Modifier.fillMaxSize().background(MotoGPBlack)) {
        if (topImageUrl != null) {
            AsyncImage(
                model = topImageUrl, contentDescription = null, contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(), alpha = 0.3f
            )
            Box(modifier = Modifier.fillMaxSize().background(
                Brush.verticalGradient(colors = listOf(Color.Transparent, MotoGPBlack, MotoGPBlack))
            ))
        }

        Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
            Spacer(modifier = Modifier.height(32.dp))
            IconButton(
                onClick = onBackClick,
                modifier = Modifier.background(GlassWhite, RoundedCornerShape(50))
            ) {
                Icon(Icons.Default.ArrowBack, contentDescription = "Back", tint = Color.White)
            }

            Spacer(modifier = Modifier.weight(0.3f))

            Column(
                modifier = Modifier.fillMaxWidth().glassmorphism(cornerRadius = 24).padding(20.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (flagUrl != null) {
                        AsyncImage(model = flagUrl, contentDescription = "Flag", modifier = Modifier.size(32.dp).clip(RoundedCornerShape(4.dp)))
                        Spacer(modifier = Modifier.width(12.dp))
                    }
                    Text(event.circuit?.country?.uppercase() ?: "", color = MotoGPRed, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
                Spacer(modifier = Modifier.height(8.dp))
                Text(event.circuit?.name ?: event.name, color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Black, lineHeight = 28.sp)
                
                Spacer(modifier = Modifier.height(16.dp))
                Divider(color = Color.White.copy(alpha = 0.1f))
                Spacer(modifier = Modifier.height(16.dp))

                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Column {
                        Text("PANJANG", color = TextGray, fontSize = 10.sp)
                        Text("${event.circuit?.track?.lenght_units?.kiloMeters ?: "-"} km", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                    }
                    Column {
                        Text("KAPASITAS", color = TextGray, fontSize = 10.sp)
                        Text("${event.circuit?.capacity ?: "-"}", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text("PILIH SESI", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                if (matchStatus.isNotEmpty()) {
                    Text(matchStatus, color = MotoGPRed, fontSize = 12.sp)
                }
            }
            Spacer(modifier = Modifier.height(12.dp))
            
            val sessions = listOf("FP1", "FP2", "Q1", "Q2", "SPRINT", "RACE")
            LazyVerticalGrid(
                columns = GridCells.Fixed(3),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                modifier = Modifier.height(150.dp)
            ) {
                items(sessions) { sesi ->
                    Box(
                        modifier = Modifier.height(60.dp).clip(RoundedCornerShape(12.dp)).background(Color(0xFF222222))
                            .bouncyClickable {
                                if (loadingSession == null) {
                                    loadingSession = sesi
                                    matchStatus = "Mencari link $sesi..."
                                    scope.launch {
                                        val country = event.circuit?.country ?: ""
                                        val eventUrl = scraper.findEventUrl(country, 2026)
                                        
                                        if (eventUrl != null) {
                                            val embedUrl = scraper.getEmbedUrl(eventUrl, sesi)
                                            loadingSession = null
                                            matchStatus = ""
                                            
                                            if (embedUrl != null) {
                                                onSessionClick(embedUrl)
                                            } else {
                                                Toast.makeText(context, "Video $sesi belum tersedia di MotoMundo", Toast.LENGTH_SHORT).show()
                                            }
                                        } else {
                                            loadingSession = null
                                            matchStatus = "URL MotoMundo tidak ditemukan"
                                            Toast.makeText(context, "Gagal nemu halaman balapan $country di MotoMundo", Toast.LENGTH_SHORT).show()
                                        }
                                    }
                                }
                            },
                        contentAlignment = Alignment.Center
                    ) {
                        if (loadingSession == sesi) {
                            CircularProgressIndicator(color = MotoGPRed, modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
                        } else {
                            Text(sesi, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                        }
                    }
                }
            }
            Spacer(modifier = Modifier.height(32.dp))
        }
    }
}
