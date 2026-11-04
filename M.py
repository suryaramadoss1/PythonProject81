import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import folium
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium


MODEL_BASE_URL = "https://api.meta.ai/v1"
MODEL_NAME = "muse-spark-1.3"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
META_API_KEY = os.environ.get("META_API_KEY", "").strip()
API_HEADERS = {
    "User-Agent": "WorldMapLocationApp/1.0",
    "Accept": "application/json",
}
HAND_DIRECTION_COMPONENT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{color:#262730;font-family:sans-serif;margin:0}
button{background:#2563eb;border:0;border-radius:.4rem;color:white;cursor:pointer;font-size:.95rem;margin:.25rem .35rem .25rem 0;padding:.55rem .85rem}
button:disabled{cursor:not-allowed;opacity:.55}
video{background:#111827;border-radius:.4rem;display:block;margin-top:.5rem;max-height:240px;max-width:100%}
#status{margin:.4rem 0;min-height:1.3rem}
</style>
</head>
<body>
<button id="start">Start hand tracking</button>
<button id="use" disabled>Use this direction</button>
<button id="stop" disabled>Stop camera</button>
<div id="status" role="status">Camera is off.</div>
<video id="preview" autoplay muted playsinline></video>
<script type="module">
const startButton=document.getElementById("start");
const useButton=document.getElementById("use");
const stopButton=document.getElementById("stop");
const status=document.getElementById("status");
const video=document.getElementById("preview");
const compass=["N","NE","E","SE","S","SW","W","NW"];
let landmarker,stream,frame,latestHeading,samples=[];
function send(type,data={}){window.parent.postMessage({isStreamlitMessage:true,type,...data},"*")}
function label(value){return compass[Math.round(value/45)%8]}
function distance(point,wrist){return Math.hypot(point.x-wrist.x,point.y-wrist.y)}
function getHeading(points){
  const wrist=points[0],mcp=points[5],pip=points[6],tip=points[8];
  if(distance(tip,wrist)<=distance(pip,wrist)*1.1)return null;
  for(const [joint,end] of [[10,12],[14,16],[18,20]]){
    if(distance(points[end],wrist)>=distance(points[joint],wrist))return null;
  }
  const dx=tip.x-mcp.x,dy=tip.y-mcp.y;
  if(Math.hypot(dx,dy)<.08)return null;
  return (Math.atan2(-dy,dx)*180/Math.PI+360)%360;
}
function smooth(value){
  samples=[...samples,value].slice(-8);
  const angles=samples.map(item=>item*Math.PI/180);
  const x=angles.reduce((sum,item)=>sum+Math.cos(item),0);
  const y=angles.reduce((sum,item)=>sum+Math.sin(item),0);
  return (Math.atan2(y,x)*180/Math.PI+360)%360;
}
function detect(timestamp){
  if(!stream||!landmarker)return;
  if(video.readyState>=HTMLMediaElement.HAVE_CURRENT_DATA){
    const points=landmarker.detectForVideo(video,timestamp).landmarks?.[0];
    const heading=points?getHeading(points):null;
    if(heading===null){
      latestHeading=undefined;samples=[];useButton.disabled=true;
      status.textContent=points?"Extend your index finger and curl the others.":"Show one hand and point with your index finger.";
    }else{
      latestHeading=smooth(heading);useButton.disabled=false;
      status.textContent=`Pointing ${label(latestHeading)} (${Math.round(latestHeading)}° from north).`;
    }
  }
  frame=requestAnimationFrame(detect);
}
function stopCamera(){
  if(frame){cancelAnimationFrame(frame);frame=undefined}
  if(stream){stream.getTracks().forEach(track=>track.stop());stream=undefined}
  video.srcObject=null;latestHeading=undefined;samples=[];
  useButton.disabled=true;stopButton.disabled=true;startButton.disabled=false;
  if(landmarker){landmarker.close();landmarker=undefined}
  status.textContent="Camera is off.";
}
async function startCamera(){
  startButton.disabled=true;status.textContent="Requesting camera access...";
  try{
    stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:"user"}});
    video.srcObject=stream;await video.play();
    status.textContent="Loading hand tracking in your browser...";
    const {FilesetResolver,HandLandmarker}=await import("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision/vision_bundle.mjs");
    const vision=await FilesetResolver.forVisionTasks("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision/wasm");
    const options={baseOptions:{modelAssetPath:"https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"},runningMode:"VIDEO",numHands:1};
    try{landmarker=await HandLandmarker.createFromOptions(vision,{...options,baseOptions:{...options.baseOptions,delegate:"GPU"}})}
    catch{status.textContent="GPU unavailable; starting on CPU...";landmarker=await HandLandmarker.createFromOptions(vision,{...options,baseOptions:{...options.baseOptions,delegate:"CPU"}})}
    stopButton.disabled=false;status.textContent="Point your index finger in a compass direction.";frame=requestAnimationFrame(detect);
  }catch(error){stopCamera();status.textContent=`Could not start hand tracking: ${error.message||error}. Check camera permission and network access.`}
}
startButton.addEventListener("click",startCamera);
stopButton.addEventListener("click",stopCamera);
useButton.addEventListener("click",()=>{
  if(latestHeading===undefined)return;
  const selected=latestHeading;
  send("streamlit:setComponentValue",{value:{heading:selected},dataType:"json"});
  stopCamera();status.textContent=`Direction selected: ${label(selected)}.`;
});
window.addEventListener("pagehide",stopCamera);
send("streamlit:componentReady",{apiVersion:1});
send("streamlit:setFrameHeight",{height:330});
</script>
</body>
</html>
"""
component_directories = (
    Path(__file__).resolve().parent / "hand_direction_component",
    Path.cwd() / "hand_direction_component",
)
component_directory = next(
    (
        directory
        for directory in component_directories
        if (directory / "index.html").is_file()
    ),
    None,
)
if component_directory is None:
    component_directory = (
        Path(tempfile.gettempdir()) / "world_map_hand_direction_component"
    )
    component_directory.mkdir(parents=True, exist_ok=True)
    (component_directory / "index.html").write_text(
        HAND_DIRECTION_COMPONENT_HTML,
        encoding="utf-8",
    )
hand_direction_component = components.declare_component(
    "hand_direction",
    path=str(component_directory),
)

st.set_page_config(page_title="World Map Explorer", layout="wide")
st.title("World Map Explorer")
st.caption(
    "Click the map to explore nearby Wikipedia places, get recommendations, "
    "and see the great-circle route between your first two clicks."
)


def request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    last_error: requests.RequestException | None = None
    headers = {**API_HEADERS, **kwargs.pop("headers", {})}
    for attempt in range(3):
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("The API returned an unexpected response.")
            return payload
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    if last_error is not None:
        raise RuntimeError(f"Connection failed after 3 attempts: {last_error}")
    raise RuntimeError("The API request failed.")


@st.cache_data(ttl=600, show_spinner=False)
def get_nearby_wikipedia_places(
    latitude: float,
    longitude: float,
    radius_m: int = 10_000,
    limit: int = 30,
) -> list[dict[str, Any]]:
    search = request_json(
        "GET",
        WIKIPEDIA_API,
        params={
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{latitude}|{longitude}",
            "gsradius": min(max(radius_m, 1), 10_000),
            "gslimit": min(max(limit, 1), 50),
            "format": "json",
        },
        timeout=(5, 20),
    )
    nearby = search.get("query", {}).get("geosearch", [])
    if not nearby:
        return []

    page_ids = "|".join(str(place["pageid"]) for place in nearby)
    details = request_json(
        "GET",
        WIKIPEDIA_API,
        params={
            "action": "query",
            "pageids": page_ids,
            "prop": "pageimages|extracts|info",
            "piprop": "thumbnail",
            "pithumbsize": 500,
            "inprop": "url",
            "exintro": 1,
            "explaintext": 1,
            "exchars": 500,
            "format": "json",
            "formatversion": 2,
        },
        timeout=(5, 20),
    )
    pages = {
        page["pageid"]: page
        for page in details.get("query", {}).get("pages", [])
    }
    results = []
    for place in nearby:
        page = pages.get(place["pageid"], {})
        results.append(
            {
                "name": place["title"],
                "lat": float(place["lat"]),
                "lon": float(place["lon"]),
                "distance_km": float(place["dist"]) / 1000,
                "url": page.get("fullurl")
                or f"https://en.wikipedia.org/?curid={place['pageid']}",
                "summary": page.get("extract", ""),
                "image": page.get("thumbnail", {}).get("source"),
            }
        )
    return results


def get_model_recommendations(api_key: str, context: dict[str, Any]) -> str:
    response = requests.post(
        f"{MODEL_BASE_URL.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL_NAME,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Give concise recommendations based only on the "
                        "selected coordinates and nearby Wikipedia results."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False),
                },
            ],
            "temperature": 0.4,
            "max_tokens": 500,
        },
        timeout=45,
    )
    if not response.ok:
        raise RuntimeError(
            f"Model API returned HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )
    try:
        answer = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(
            "The model response did not match the expected chat-completions format."
        ) from exc
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("The model API returned an empty response.")
    return answer.strip()


def great_circle_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
    segments: int = 96,
) -> list[tuple[float, float]]:
    def to_unit_vector(
        point: tuple[float, float],
    ) -> tuple[float, float, float]:
        latitude, longitude = map(math.radians, point)
        return (
            math.cos(latitude) * math.cos(longitude),
            math.cos(latitude) * math.sin(longitude),
            math.sin(latitude),
        )

    start = to_unit_vector(origin)
    end = to_unit_vector(destination)
    dot_product = max(-1.0, min(1.0, sum(a * b for a, b in zip(start, end))))
    angle = math.acos(dot_product)
    if angle < 1e-10:
        return [origin, destination]

    if math.pi - angle < 1e-10:
        axis = (1.0, 0.0, 0.0) if abs(start[0]) < 0.9 else (0.0, 1.0, 0.0)
        perpendicular = (
            start[1] * axis[2] - start[2] * axis[1],
            start[2] * axis[0] - start[0] * axis[2],
            start[0] * axis[1] - start[1] * axis[0],
        )
        length = math.sqrt(sum(component**2 for component in perpendicular))
        perpendicular = tuple(component / length for component in perpendicular)

        def point_at(fraction: float) -> tuple[float, float, float]:
            return tuple(
                start[index] * math.cos(math.pi * fraction)
                + perpendicular[index] * math.sin(math.pi * fraction)
                for index in range(3)
            )

    else:
        sine_angle = math.sin(angle)

        def point_at(fraction: float) -> tuple[float, float, float]:
            start_weight = math.sin((1 - fraction) * angle) / sine_angle
            end_weight = math.sin(fraction * angle) / sine_angle
            return tuple(
                start[index] * start_weight + end[index] * end_weight
                for index in range(3)
            )

    route = []
    for index in range(segments + 1):
        x, y, z = point_at(index / segments)
        route.append(
            (
                math.degrees(math.atan2(z, math.hypot(x, y))),
                math.degrees(math.atan2(y, x)),
            )
        )
    return route


def split_route_at_antimeridian(
    route: list[tuple[float, float]],
) -> list[list[tuple[float, float]]]:
    if not route:
        return []
    route_segments = [[route[0]]]
    for (start_lat, start_lon), (end_lat, end_lon) in zip(route, route[1:]):
        longitude_delta = end_lon - start_lon
        if abs(longitude_delta) <= 180:
            route_segments[-1].append((end_lat, end_lon))
            continue
        adjusted_end_lon = end_lon - math.copysign(360, longitude_delta)
        boundary = 180 if start_lon >= 0 else -180
        fraction = (boundary - start_lon) / (adjusted_end_lon - start_lon)
        crossing_lat = start_lat + fraction * (end_lat - start_lat)
        route_segments[-1].append((crossing_lat, boundary))
        route_segments.append([(crossing_lat, -boundary), (end_lat, end_lon)])
    return route_segments


def great_circle_distance_miles(
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> float:
    latitude1, longitude1 = map(math.radians, origin)
    latitude2, longitude2 = map(math.radians, destination)
    delta_latitude = latitude2 - latitude1
    delta_longitude = longitude2 - longitude1
    haversine = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude1)
        * math.cos(latitude2)
        * math.sin(delta_longitude / 2) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    angle = 2 * math.atan2(
        math.sqrt(haversine),
        math.sqrt(1 - haversine),
    )
    return 3958.7613 * angle


def compass_direction(bearing: float) -> str:
    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return directions[int((bearing + 22.5) // 45) % len(directions)]


def get_directional_recommendations(
    origin: tuple[float, float],
    places: list[dict[str, Any]],
    heading: float,
    tolerance: float = 45,
) -> list[dict[str, Any]]:
    latitude1, longitude1 = map(math.radians, origin)
    recommendations: list[dict[str, Any]] = []
    for place in places:
        latitude2 = math.radians(place["lat"])
        longitude2 = math.radians(place["lon"])
        delta_longitude = longitude2 - longitude1
        east_component = math.sin(delta_longitude) * math.cos(latitude2)
        north_component = (
            math.cos(latitude1) * math.sin(latitude2)
            - math.sin(latitude1)
            * math.cos(latitude2)
            * math.cos(delta_longitude)
        )
        bearing = math.degrees(math.atan2(east_component, north_component)) % 360
        angular_difference = abs((bearing - heading + 180) % 360 - 180)
        if angular_difference <= tolerance:
            recommendations.append(
                {
                    **place,
                    "bearing": bearing,
                    "angular_difference": angular_difference,
                }
            )
    return sorted(
        recommendations,
        key=lambda place: (
            place["angular_difference"],
            place["distance_km"],
        ),
    )


def speak(messages: list[str]) -> None:
    encoded_messages = json.dumps(messages)
    components.html(
        f"""
        <script>
        const messages = {encoded_messages};
        const synth = window.speechSynthesis;
        if (synth) {{
            synth.cancel();
            for (const message of messages) {{
                const utterance = new SpeechSynthesisUtterance(message);
                utterance.lang = "en-US";
                synth.speak(utterance);
            }}
        }}
        </script>
        """,
        height=1,
    )


defaults = {
    "selected_point": None,
    "origin": None,
    "destination": None,
    "last_click_seen": None,
    "last_announcement": None,
    "map_generation": 0,
    "hand_direction": None,
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

if st.button("Clear map and selections"):
    next_map_generation = st.session_state.map_generation + 1
    for key, value in defaults.items():
        st.session_state[key] = value
    st.session_state.map_generation = next_map_generation
    st.rerun()

selected_point = st.session_state.selected_point
nearby_places: list[dict[str, Any]] = []
directional_places: list[dict[str, Any]] = []

if selected_point is not None:
    latitude, longitude = selected_point
    st.subheader("Selected location")
    st.write(f"Latitude: `{latitude:.6f}` · Longitude: `{longitude:.6f}`")
    st.subheader("Point to get direction-based suggestions")
    st.caption(
        "Allow camera access and point your index finger in the desired "
        "direction (up is north; right is east in the preview). Choose Use "
        "this direction to see nearby suggestions. Video stays in your "
        "browser; only the selected direction is shared with this app."
    )
    gesture_result = hand_direction_component(
        key=(
            f"hand-direction-{st.session_state.map_generation}-"
            f"{latitude:.5f}-{longitude:.5f}"
        ),
        default=None,
    )
    if isinstance(gesture_result, dict):
        try:
            heading = float(gesture_result.get("heading"))
        except (TypeError, ValueError):
            heading = math.nan
        if math.isfinite(heading) and 0 <= heading < 360:
            st.session_state.hand_direction = heading

    heading = st.session_state.hand_direction
    if heading is not None:
        direction_label = compass_direction(heading)
        st.success(
            f"Detected direction: **{direction_label}** "
            f"({heading:.0f}° from north)"
        )
    try:
        nearby_places = get_nearby_wikipedia_places(latitude, longitude)
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
        st.warning(f"Could not load nearby Wikipedia places: {exc}")

    if heading is not None:
        directional_places = get_directional_recommendations(
            selected_point,
            nearby_places,
            heading,
        )
        st.subheader(f"Places in the {direction_label} direction")
        if directional_places:
            for place in directional_places[:5]:
                st.markdown(
                    f"[{place['name']}]({place['url']}) "
                    f"— {place['distance_km']:.1f} km away"
                )
        else:
            st.info(
                "No nearby Wikipedia places were found within 45° of that "
                "direction. Try another pointing direction."
            )

    st.subheader("Nearby Wikipedia places")
    if nearby_places:
        for index, place in enumerate(nearby_places):
            st.markdown(
                f"[{place['name']}]({place['url']}) "
                f"— {place['distance_km']:.1f} km away"
            )
            if index < 5 and place["image"]:
                st.image(place["image"], width=300)
            if place["summary"]:
                st.write(place["summary"])
    else:
        st.info("No nearby Wikipedia places were found.")

    if not META_API_KEY:
        st.info("Set the META_API_KEY environment variable to enable AI recommendations.")
    elif st.button("Generate recommendations"):
        context = {
            "selected_coordinates": {
                "latitude": latitude,
                "longitude": longitude,
            },
            "nearby_wikipedia_articles": [
                {
                    "title": place["name"],
                    "distance_km": round(place["distance_km"], 2),
                    "summary": place["summary"],
                }
                for place in nearby_places
            ],
        }
        try:
            with st.spinner("Generating recommendations..."):
                st.write(get_model_recommendations(META_API_KEY, context))
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            st.error(f"Could not generate recommendations: {exc}")

if st.session_state.origin is not None:
    st.caption("The first map click is the origin; the second is the destination.")

map_center = selected_point if selected_point is not None else (20.0, 0.0)
map_zoom = 4 if selected_point is not None else 2
world_map = folium.Map(
    location=map_center,
    zoom_start=map_zoom,
    min_zoom=2,
    tiles="OpenStreetMap",
    control_scale=True,
)

route_layer = folium.FeatureGroup(name="Selections and great-circle route", show=True)
landmark_layer = folium.FeatureGroup(name="Nearby Wikipedia places", show=True)

if st.session_state.origin is not None:
    folium.Marker(
        st.session_state.origin,
        tooltip="Origin",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(route_layer)

if st.session_state.destination is not None:
    folium.Marker(
        st.session_state.destination,
        tooltip="Destination",
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(route_layer)

if (
    st.session_state.origin is not None
    and st.session_state.destination is not None
):
    origin = st.session_state.origin
    destination = st.session_state.destination
    great_circle = great_circle_route(origin, destination)
    for segment in split_route_at_antimeridian(great_circle):
        folium.PolyLine(
            segment,
            color="#2563eb",
            weight=3,
            opacity=0.85,
            tooltip="Great-circle route",
        ).add_to(route_layer)
    distance = great_circle_distance_miles(origin, destination)
    st.caption(f"Great-circle distance: {distance:,.1f} miles.")

if selected_point is not None:
    folium.Marker(
        selected_point,
        tooltip="Selected location",
        popup=(
            f"Latitude: {selected_point[0]:.6f}, "
            f"longitude: {selected_point[1]:.6f}"
        ),
        icon=folium.Icon(color="cadetblue", icon="info-sign"),
    ).add_to(route_layer)

recommended_names = {place["name"] for place in directional_places}
for place in nearby_places:
    is_recommended = place["name"] in recommended_names
    popup = folium.Popup(
        f"<b>{place['name']}</b><br>{place['distance_km']:.1f} km away",
        max_width=300,
    )
    folium.Marker(
        [place["lat"], place["lon"]],
        tooltip=place["name"],
        popup=popup,
        icon=folium.Icon(
            color="green" if is_recommended else "blue",
            icon="star" if is_recommended else "book",
        ),
    ).add_to(landmark_layer)

route_layer.add_to(world_map)
landmark_layer.add_to(world_map)
folium.LayerControl(collapsed=False).add_to(world_map)

if st.session_state.origin is not None and st.session_state.destination is not None:
    world_map.fit_bounds(
        [st.session_state.origin, st.session_state.destination],
        padding=(30, 30),
        max_zoom=6,
    )

map_result = st_folium(
    world_map,
    key=f"world-map-{st.session_state.map_generation}",
    height=600,
    use_container_width=True,
    returned_objects=["last_clicked"],
)

last_clicked = (map_result or {}).get("last_clicked")
if last_clicked is not None:
    latitude = last_clicked.get("lat")
    longitude = last_clicked.get("lng", last_clicked.get("lon"))
    if latitude is None or longitude is None:
        st.error("The map click did not include latitude and longitude.")
    else:
        try:
            point = (float(latitude), float(longitude))
        except (TypeError, ValueError):
            st.error("The clicked coordinates must be numbers.")
        else:
            is_valid_point = (
                math.isfinite(point[0])
                and math.isfinite(point[1])
                and -90 <= point[0] <= 90
                and -180 <= point[1] <= 180
            )
            if not is_valid_point:
                st.error("The clicked coordinates are outside the valid ranges.")
            elif point != st.session_state.last_click_seen:
                st.session_state.last_click_seen = point
                st.session_state.selected_point = point
                st.session_state.hand_direction = None
                if st.session_state.origin is None:
                    st.session_state.origin = point
                    st.session_state.last_announcement = [
                        f"Origin selected. Latitude {point[0]:.5f}, "
                        f"longitude {point[1]:.5f}."
                    ]
                elif st.session_state.destination is None:
                    st.session_state.destination = point
                    distance = great_circle_distance_miles(
                        st.session_state.origin,
                        point,
                    )
                    st.session_state.last_announcement = [
                        f"Destination selected. Latitude {point[0]:.5f}, "
                        f"longitude {point[1]:.5f}.",
                        f"The route distance is {distance:,.1f} miles.",
                    ]
                st.rerun()

if st.session_state.last_announcement:
    speak(st.session_state.last_announcement)
    st.session_state.last_announcement = None
