from auth import CXoneAuthenticator
from fetch_recordings import RecordingFetcher

auth = CXoneAuthenticator()
fetcher = RecordingFetcher(auth)

files = fetcher.fetch_and_download(693159199085);