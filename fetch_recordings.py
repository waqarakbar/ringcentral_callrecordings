"""
NICE inContact CXone Call Recording Fetcher

This module fetches call recording metadata and downloads audio files
from the CXone Media Playback API.
"""

import os
import json
import base64
import requests
from pathlib import Path
from typing import Dict, Optional, List
from auth import CXoneAuthenticator


class RecordingNotFoundException(Exception):
    """Raised when a recording is not found for a given contact ID."""
    pass



class RecordingFetcher:
    """
    Handles fetching and downloading call recordings from CXone API.
    
    Attributes:
        authenticator: CXoneAuthenticator instance for API authentication
        base_url: Base URL for API calls (e.g., https://api-au1.niceincontact.com)
        recordings_dir: Directory path for saving downloaded recordings
    """
    
    def __init__(self, authenticator: CXoneAuthenticator, recordings_dir: str = "recordings"):
        """
        Initialize the RecordingFetcher.
        
        Args:
            authenticator: CXoneAuthenticator instance
            recordings_dir: Directory to save downloaded recordings (default: "recordings")
        """
        self.authenticator = authenticator
        self.recordings_dir = Path(recordings_dir)
        self.base_url = None
        
        # Create recordings directory if it doesn't exist
        self.recordings_dir.mkdir(exist_ok=True)
        
        # Extract the correct API base URL from token
        self._extract_base_url()
    
    def _extract_base_url(self) -> None:
        """
        Extract the area from the authentication token to construct the base URL.
        The base URL format is: https://api-{area}.niceincontact.com
        """
        # Authenticate to get the ID token
        auth_response = self.authenticator.authenticate()
        
        id_token = auth_response.get("id_token")
        if not id_token:
            raise ValueError("No id_token in authentication response")
        
        # JWT format: header.payload.signature
        try:
            payload_part = id_token.split('.')[1]
            # Add padding if needed
            padding = len(payload_part) % 4
            if padding:
                payload_part += '=' * (4 - padding)
            
            payload = json.loads(base64.b64decode(payload_part))
            
            # Extract 'area' field (e.g., 'au1')
            area = payload.get("area", "")
            
            if not area:
                raise ValueError("'area' field not found in token payload")
            
            # Construct base URL
            self.base_url = f"https://api-{area}.niceincontact.com/media-playback/v1"
            
            print(f"✓ Detected area: {area}")
            print(f"  API Base URL: {self.base_url}")
            
        except Exception as e:
            raise ValueError(f"Failed to extract area from token: {str(e)}")
    
    def get_recording_metadata(
        self,
        contact_id: str,
        is_download: bool = False,
        media_type: str = "all",
        exclude_waveforms: bool = True,
        exclude_qm_categories: bool = False
    ) -> Dict:
        """
        Fetch recording metadata for a given contact ID.
        
        Args:
            contact_id: The contact/ACD call ID
            is_download: Set to True to get downloadable URL (default: False)
            media_type: Filter by media type: 'all', 'voice-only', 'voice-and-screen'
            exclude_waveforms: Exclude waveform data (default: True)
            exclude_qm_categories: Exclude QM categories (default: False)
        
        Returns:
            Dict containing the API response with recording metadata
        
        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        endpoint = f"{self.base_url}/contacts"
        
        headers = self.authenticator.get_auth_header()
        headers["accept"] = "application/json"
        
        params = {
            "acd-call-id": contact_id,
            "media-type": media_type,
            "exclude-waveforms": str(exclude_waveforms).lower(),
            "exclude-qm-categories": str(exclude_qm_categories).lower(),
            "isDownload": str(is_download).lower()
        }
        
        print(f"\n🔍 Fetching recording metadata for contact ID: {contact_id}")
        print(f"  URL: {endpoint}")
        print(f"  Parameters: {params}")
        
        try:
            response = requests.get(
                endpoint,
                headers=headers,
                params=params,
                timeout=30
            )
            
            response.raise_for_status()
            metadata = response.json()
            
            print(f"✓ Successfully retrieved metadata")
            
            return metadata
            
        except requests.exceptions.HTTPError as e:
            # Handle 404 specifically - recording not found
            if e.response is not None and e.response.status_code == 404:
                error_detail = {}
                try:
                    error_detail = e.response.json()
                except:
                    pass
                
                error_msg = (
                    f"\n⚠️  Recording not found for contact ID: {contact_id}\n"
                    f"   This contact either:\n"
                    f"   - Doesn't exist in the system\n"
                    f"   - Doesn't have a recording\n"
                    f"   - Recording has expired or been deleted\n"
                    f"   \n"
                    f"   API Response: {error_detail.get('message', 'Not found')}"
                )
                raise RecordingNotFoundException(error_msg)
            
            # Handle other HTTP errors
            error_msg = f"HTTP Error fetching metadata: {e}"
            if e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg += f"\nDetails: {error_detail}"
                except:
                    error_msg += f"\nResponse: {e.response.text}"
            raise requests.exceptions.RequestException(error_msg)
        
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.RequestException(
                f"Failed to fetch metadata: {str(e)}"
            )
    
    def extract_file_urls(self, metadata: Dict) -> List[Dict[str, str]]:
        """
        Extract fileToPlayUrl from metadata response.
        
        Args:
            metadata: The API response containing recording metadata
        
        Returns:
            List of dicts containing media_type and fileToPlayUrl
        """
        file_urls = []
        
        interactions = metadata.get("interactions", [])
        
        if not interactions:
            print("⚠ No interactions found in metadata")
            return file_urls
        
        for interaction in interactions:
            media_type = interaction.get("mediaType", "unknown")
            data = interaction.get("data", {})
            file_url = data.get("fileToPlayUrl")
            
            if file_url:
                file_urls.append({
                    "media_type": media_type,
                    "url": file_url
                })
                print(f"  ✓ Found {media_type} file URL")
        
        return file_urls
    
    def download_recording(
        self,
        file_url: str,
        contact_id: str,
        media_type: str = "voice"
    ) -> Path:
        """
        Download recording file from the provided URL.
        
        Args:
            file_url: The URL to download the file from
            contact_id: Contact ID to use in filename
            media_type: Type of media for filename (default: 'voice')
        
        Returns:
            Path to the downloaded file
        
        Raises:
            requests.exceptions.RequestException: If download fails
        """
        # Determine file extension from URL or default to .mp3
        file_ext = ".mp3"
        if "." in file_url.split("/")[-1]:
            url_part = file_url.split(".")[-1].split("?")[0]
            if url_part:
                file_ext = "." + url_part
        
        # Create filename with contact_id prefix
        filename = f"{contact_id}_{media_type}{file_ext}"
        filepath = self.recordings_dir / filename
        
        print(f"\n📥 Downloading recording...")
        print(f"  File: {filename}")
        print(f"  Location: {filepath}")
        
        try:
            # Stream download for large files
            response = requests.get(file_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Get file size if available
            total_size = int(response.headers.get('content-length', 0))
            
            # Download in chunks
            chunk_size = 8192
            downloaded = 0
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Show progress
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            print(f"\r  Progress: {progress:.1f}% ({downloaded:,}/{total_size:,} bytes)", end="", flush=True)
            
            print(f"\n✓ Successfully downloaded: {filepath}")
            print(f"  File size: {downloaded:,} bytes")
            
            return filepath
            
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.RequestException(
                f"Failed to download recording: {str(e)}"
            )
    
    def fetch_and_download(self, contact_id: str) -> List[Path]:
        """
        Fetch metadata and download all recordings for a contact ID.
        
        Args:
            contact_id: The contact/ACD call ID
        
        Returns:
            List of paths to downloaded files
        """
        downloaded_files = []
        
        try:
            # Get metadata
            metadata = self.get_recording_metadata(contact_id)
            
            print(f"\n📋 Metadata Response:")
            print(json.dumps(metadata, indent=2))
            
            # Extract file URLs
            file_urls = self.extract_file_urls(metadata)
            
            if not file_urls:
                print("\n⚠ No recording files found")
                return downloaded_files
            
            # Download each file
            for file_info in file_urls:
                filepath = self.download_recording(
                    file_info["url"],
                    contact_id,
                    file_info["media_type"]
                )
                downloaded_files.append(filepath)
            
            return downloaded_files
            
        except RecordingNotFoundException as e:
            print(str(e))
            print("\n💡 Tip: Use a contact ID that has an available recording.")
            print("   The contact ID 479367298239 worked successfully in testing.")
            return downloaded_files
            
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            raise


def main():
    """
    Example usage: Fetch and download recording for a specific contact ID.
    """
    # Contact ID to fetch (you can change this)
    CONTACT_ID = "693159199085"  # Use a valid contact ID with recording
    
    try:
        # Initialize authenticator
        print("="*70)
        print("CXone Recording Fetcher")
        print("="*70)
        
        auth = CXoneAuthenticator()
        
        # Initialize fetcher
        fetcher = RecordingFetcher(auth)
        
        # Fetch and download recordings
        downloaded_files = fetcher.fetch_and_download(CONTACT_ID)
        
        # Summary
        print("\n" + "="*70)
        print("Download Summary")
        print("="*70)
        print(f"Contact ID: {CONTACT_ID}")
        print(f"Files downloaded: {len(downloaded_files)}")
        for filepath in downloaded_files:
            print(f"  📁 {filepath}")
        print("="*70)
        
    except RecordingNotFoundException:
        # Already handled with user-friendly message
        return 1
        
    except Exception as e:
        print(f"\n❌ Unexpected Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
