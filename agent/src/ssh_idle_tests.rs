//! Real in-memory SSH transport, never a network listener or real credential.

use super::*;
use russh::server;

struct Echo;

impl server::Handler for Echo {
    type Error = russh::Error;

    async fn auth_password(&mut self, _: &str, _: &str) -> Result<server::Auth, Self::Error> {
        Ok(server::Auth::Accept)
    }

    async fn channel_open_session(
        &mut self,
        _: Channel<server::Msg>,
        reply: server::ChannelOpenHandle,
        _: &mut server::Session,
    ) -> Result<(), Self::Error> {
        reply.accept().await;
        Ok(())
    }

    async fn data(
        &mut self,
        channel: russh::ChannelId,
        data: &[u8],
        session: &mut server::Session,
    ) -> Result<(), Self::Error> {
        session.data(channel, data.to_vec())
    }
}

async fn connected(
    idle: Duration,
) -> Result<(client::Handle<HostKeyVerifier>, Channel<client::Msg>)> {
    // Deliberately public deterministic fixture seed; never used outside this test.
    let key = russh::keys::PrivateKey::new(
        russh::keys::ssh_key::private::Ed25519Keypair::from_seed(&[42; 32]).into(),
        "synthetic-idle-transport-only",
    )?;
    // SSH wire keys carry no OpenSSH display comment, as in real inventory pins.
    let mut pinned = key.public_key().clone();
    pinned.set_comment("");
    let configuration = server::Config {
        keys: vec![key],
        auth_rejection_time: Duration::ZERO,
        auth_rejection_time_initial: Some(Duration::ZERO),
        ..Default::default()
    };
    let (local, remote) = tokio::io::duplex(65536);
    tokio::spawn(async move {
        if let Ok(session) = server::run_stream(Arc::new(configuration), remote, Echo).await {
            let _ = session.await;
        }
    });
    let mut handle = client::connect_stream(
        Arc::new(SshSession::configuration(idle)),
        local,
        HostKeyVerifier { pinned },
    )
    .await?;
    assert!(
        handle
            .authenticate_password("synthetic", "synthetic")
            .await?
            .success()
    );
    let channel = handle.channel_open_session().await?;
    Ok((handle, channel))
}

async fn echo(channel: &mut Channel<client::Msg>) -> Result<()> {
    channel.data_bytes(b"synthetic-check".as_slice()).await?;
    match timeout(Duration::from_secs(3), channel.wait()).await? {
        Some(russh::ChannelMsg::Data { data }) if data.as_ref() == b"synthetic-check" => Ok(()),
        _ => bail!("synthetic SSH echo was not returned"),
    }
}

#[tokio::test]
async fn local_processing_gap_closes_old_idle_but_not_bounded_cycle_transport() -> Result<()> {
    timeout(Duration::from_secs(25), async {
        let (old, mut old_channel) = connected(Duration::from_secs(15)).await?;
        let (new, mut new_channel) = connected(cycle::max_duration(6)).await?;
        echo(&mut old_channel).await?;
        echo(&mut new_channel).await?;
        // No SSH packets/keepalives or CLI during this local-processing interval.
        tokio::time::sleep(Duration::from_secs(16)).await;
        assert!(old.is_closed());
        assert!(!new.is_closed());
        echo(&mut new_channel).await?;
        new.disconnect(Disconnect::ByApplication, "", "en").await?;
        Ok(())
    })
    .await?
}

#[test]
fn transport_idle_fits_existing_visit_bounds_without_changing_step_or_ipc_limits() {
    for version in 1..=7 {
        let expected = Duration::from_secs(if version >= 6 { 240 } else { 120 });
        assert_eq!(cycle::max_duration(version), expected);
        assert_eq!(
            SshSession::configuration(expected).inactivity_timeout,
            Some(expected)
        );
        assert!(
            SshSession::configuration(expected)
                .keepalive_interval
                .is_none()
        );
    }
    assert_eq!(
        SshSession::configuration(Duration::from_secs(15)).inactivity_timeout,
        Some(Duration::from_secs(15))
    );
}
